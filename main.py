import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os

# إعدادات البوت والـ Intents
intents = discord.Intents.default()
intents.message_content = True

DEFAULT_PREFIX = '!'

# دالة لدعم تغيير البريفكس ديناميكياً
async def get_prefix(bot, message):
    guild_id = message.guild.id if message.guild else None
    return custom_prefixes.get(guild_id, DEFAULT_PREFIX)

bot = commands.Bot(command_prefix=get_prefix, intents=intents)

# خزن البيانات بالذاكرة
custom_prefixes = {}       # البريفكس المخصص لكل سيرفر
playlists = {}            # البلاي ليستس الخاصة بالأعضاء {guild_id: {playlist_name: [songs]}}
queues = {}               # قائمة التشغيل الحالية {guild_id: [{"title": str, "url": str, "index": int}]}
loop_mode = {}            # وضع اللوب {guild_id: "off" | "song" | "queue"}
current_song = {}         # الأغنية الشغالة حالياً {guild_id: dict}

# إعدادات الصوت والجودة العالية
FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn -b:a 320k',
}
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'quiet': True,
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

# ==================== اللوجيك الذكي للتشغيل والـ Loop ====================

def play_next(ctx):
    guild_id = ctx.guild.id
    mode = loop_mode.get(guild_id, "off")
    
    # 1. حالة اللوب للأغنية الحالية (Song Loop)
    if mode == "song" and guild_id in current_song:
        song = current_song[guild_id]
        _start_playback(ctx, song)
        return

    # 2. حالة اللوب للقائمة كاملة (Queue Loop)
    if mode == "queue" and guild_id in current_song:
        queues[guild_id].append(current_song[guild_id])

    # 3. جلب الأغنية التالية وتخطي الإندكس الفارغ/المحذوف
    while queues.get(guild_id) and len(queues[guild_id]) > 0:
        next_song = queues[guild_id].pop(0)
        # التأكد إن الأغنية مش فارغة وبها رابط valid
        if next_song and next_song.get('url'):
            current_song[guild_id] = next_song
            _start_playback(ctx, next_song)
            return

    # لو القائمة خلصت ومافيش أغاني
    current_song.pop(guild_id, None)

def _start_playback(ctx, song):
    voice_client = ctx.voice_client
    if not voice_client:
        return
    try:
        source = discord.FFmpegPCMAudio(song['url'], **FFMPEG_OPTIONS)
        voice_client.play(source, after=lambda e: play_next(ctx))
    except Exception as e:
        print(f"خطأ في التشغيل، جاري التخطي للأغنية التالية: {e}")
        play_next(ctx) # لو فيه مشكلة في السورس بيتخطاه تلقائياً للي بعده

# ==================== الأوامــار ====================

# 1. أمر تغيير البريفكس
@bot.command(name='setprefix')
async def setprefix(ctx, new_prefix: str):
    custom_prefixes[ctx.guild.id] = new_prefix
    await ctx.send(f"✅ تم تغيير البريفكس إلى: `{new_prefix}`")

# 2. إنشاء بلاي ليست جديدة
@bot.command(name='create_playlist')
async def create_playlist(ctx, *, name: str):
    guild_id = ctx.guild.id
    if guild_id not in playlists:
        playlists[guild_id] = {}
    
    if name in playlists[guild_id]:
        await ctx.send(f"❌ البلاي ليست `{name}` موجودة بالفعل!")
    else:
        playlists[guild_id][name] = []
        await ctx.send(f"🎉 تم إنشاء البلاي ليست `{name}` بنجاح!")

# 3. إضافة أغنية للبلاي ليست بحسب الإندكس
@bot.command(name='add')
async def add_to_playlist(ctx, playlist_name: str, song_query: str, index: int = None):
    guild_id = ctx.guild.id
    if guild_id not in playlists or playlist_name not in playlists[guild_id]:
        await ctx.send(f"❌ البلاي ليست `{playlist_name}` غير موجودة!")
        return

    async with ctx.typing():
        info = ytdl.extract_info(f"ytsearch:{song_query}", download=False)
        if 'entries' in info and len(info['entries']) > 0:
            entry = info['entries'][0]
            song_data = {'title': entry['title'], 'url': entry['url']}
            
            pl = playlists[guild_id][playlist_name]
            
            if index is not None and index > 0:
                # توسيع القائمة لو الإندكس المطلوب أكبر من حجمها الحالي
                while len(pl) < index - 1:
                    pl.append(None) # إندكس فارغ
                pl.insert(index - 1, song_data)
                actual_idx = index
            else:
                pl.append(song_data)
                actual_idx = len(pl)

            await ctx.send(f"🎵 تم إضافة **{entry['title']}** إلى البلاي ليست `{playlist_name}` في الإندكس **[{actual_idx}]**!")

# 4. مسح أغنية من البلاي ليست عن طريق الإندكس فقط
@bot.command(name='remove')
async def remove_from_playlist(ctx, playlist_name: str, index: int):
    guild_id = ctx.guild.id
    if guild_id not in playlists or playlist_name not in playlists[guild_id]:
        await ctx.send(f"❌ البلاي ليست `{playlist_name}` غير موجودة!")
        return

    pl = playlists[guild_id][playlist_name]
    if index <= 0 or index > len(pl) or pl[index - 1] is None:
        await ctx.send(f"❌ لا توجد أغنية في الإندكس **[{index}]**!")
        return

    removed = pl.pop(index - 1)
    await ctx.send(f"🗑️ تم حذف **{removed['title']}** من الإندكس **[{index}]** في البلاي ليست `{playlist_name}`!")

# 5. تشغيل البلاي ليست كاملة
@bot.command(name='play_playlist')
async def play_playlist(ctx, playlist_name: str):
    guild_id = ctx.guild.id
    if guild_id not in playlists or playlist_name not in playlists[guild_id]:
        await ctx.send(f"❌ البلاي ليست `{playlist_name}` غير موجودة!")
        return

    if not ctx.author.voice:
        await ctx.send("❌ ادخل روم صوتي الأول!")
        return

    voice_channel = ctx.author.voice.channel
    if not ctx.voice_client:
        await voice_channel.connect()

    pl = playlists[guild_id][playlist_name]
    if guild_id not in queues:
        queues[guild_id] = []

    added_count = 0
    for idx, item in enumerate(pl, 1):
        if item is not None: # تخطي الإندكسات الفارغة فوراً
            queues[guild_id].append(item)
            added_count += 1

    await ctx.send(f"▶️ تم إضافة **{added_count}** أغنية من البلاي ليست `{playlist_name}` للقائمة!")

    if not ctx.voice_client.is_playing() and len(queues[guild_id]) > 0:
        play_next(ctx)

# 6. أمر تشغيل عادي أو إضافة للقائمة
@bot.command(name='play', aliases=['p'])
async def play(ctx, *, query: str):
    if not ctx.author.voice:
        await ctx.send("❌ ادخل روم صوتي الأول!")
        return

    voice_channel = ctx.author.voice.channel
    if not ctx.voice_client:
        await voice_channel.connect()

    async with ctx.typing():
        info = ytdl.extract_info(f"ytsearch:{query}", download=False)
        if 'entries' in info and len(info['entries']) > 0:
            entry = info['entries'][0]
            song = {'title': entry['title'], 'url': entry['url']}
            
            guild_id = ctx.guild.id
            if guild_id not in queues:
                queues[guild_id] = []

            queues[guild_id].append(song)

            if not ctx.voice_client.is_playing():
                play_next(ctx)
                await ctx.send(f"▶️ جاري تشغيل: **{song['title']}** بأعلى جودة!")
            else:
                await ctx.send(f"➕ تم إضافة **{song['title']}** لقائمة الانتظار!")

# 7. نظام اللوب الذكي (Smart Loop)
@bot.command(name='loop')
async def set_loop(ctx, mode: str):
    mode = mode.lower()
    guild_id = ctx.guild.id
    if mode in ['song', 'single', 'أغنية']:
        loop_mode[guild_id] = 'song'
        await ctx.send("🔂 تم تفعيل تكرار **الأغنية الحالية** طوال الوقت!")
    elif mode in ['queue', 'playlist', 'قائمة']:
        loop_mode[guild_id] = 'queue'
        await ctx.send("🔁 تم تفعيل تكرار **البلاي ليست كاملة** طوال الوقت!")
    elif mode in ['off', 'إيقاف']:
        loop_mode[guild_id] = 'off'
        await ctx.send("➡️ تم إيقاف تكرار اللوب.")
    else:
        await ctx.send("❌ اختر وضع صحيح: `!loop song` أو `!loop queue` أو `!loop off`")

# 8. أمر السكيب والإيقاف
@bot.command(name='skip', aliases=['s'])
async def skip(ctx):
    if ctx.voice_client and ctx.voice_client.is_playing():
        ctx.voice_client.stop() # إيقاف الأغنية الحالية سينقل التلقائي للتي بعدها عبر after=play_next
        await ctx.send("⏭️ تم تخطي الأغنية!")

@bot.command(name='stop')
async def stop(ctx):
    guild_id = ctx.guild.id
    queues[guild_id] = []
    loop_mode[guild_id] = 'off'
    current_song.pop(guild_id, None)
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
        await ctx.send("🛑 تم إيقاف التشغيل ومسح القائمة وخروج البوت.")

token = os.getenv('DISCORD_TOKEN')
bot.run(token)
