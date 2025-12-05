import os
import io
import re
import cv2
import numpy as np
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
from PyPDF2 import PdfReader, PdfWriter, PdfMerger
from pdf2image import convert_from_bytes
import fitz  # PyMuPDF
from collections import Counter
import tempfile
import shutil
from moviepy.editor import VideoFileClip, ImageClip, CompositeVideoClip, TextClip

BOT_TOKEN = os.getenv('BOT_TOKEN')
ALLOWED_USER_ID = int(os.getenv('ALLOWED_USER_ID'))

class PDFBot:
    def __init__(self):
        self.user_sessions = {}
    
    def get_session(self, user_id):
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = {
                'pdfs': [],
                'images': [],
                'videos': [],
                'mode': None,
                'temp_data': {},
                'common_words': []
            }
        return self.user_sessions[user_id]
    
    def clear_session_files(self, user_id):
        session = self.get_session(user_id)
        session['pdfs'] = []
        session['images'] = []
        session['videos'] = []
        session['temp_data'] = {}
        session['common_words'] = []

bot_instance = PDFBot()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        await update.message.reply_text("⛔ Unauthorized access!")
        return
    
    keyboard = [
        [InlineKeyboardButton("📄 PDF Tools", callback_data='pdf_tools')],
        [InlineKeyboardButton("🎬 Video Thumbnail", callback_data='video_tools')],
        [InlineKeyboardButton("ℹ️ Help", callback_data='help')]
    ]
    await update.message.reply_text(
        "🤖 *PDF & Video Editor Bot*\n\n"
        "Choose an option:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.from_user.id != ALLOWED_USER_ID:
        await query.message.reply_text("⛔ Unauthorized!")
        return
    
    data = query.data
    session = bot_instance.get_session(query.from_user.id)
    
    if data == 'pdf_tools':
        keyboard = [
            [InlineKeyboardButton("📤 Upload PDFs", callback_data='upload_pdf')],
            [InlineKeyboardButton("🖼️ Delete Page by Image", callback_data='delete_by_image')],
            [InlineKeyboardButton("📝 Add Watermark", callback_data='add_watermark')],
            [InlineKeyboardButton("📄 Insert Page", callback_data='insert_page')],
            [InlineKeyboardButton("🔍 Find & Replace", callback_data='find_replace')],
            [InlineKeyboardButton("📛 Rename Files", callback_data='rename_files')],
            [InlineKeyboardButton("🎨 Thumbnail Tools", callback_data='thumbnail_tools')],
            [InlineKeyboardButton("🔙 Back", callback_data='back_main')]
        ]
        await query.edit_message_text(
            "📄 *PDF Tools*\n\nSelect operation:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif data == 'upload_pdf':
        session['mode'] = 'upload_pdf'
        await query.edit_message_text("📤 Send me PDF files (one or multiple)")
    
    elif data == 'delete_by_image':
        if not session['pdfs']:
            await query.edit_message_text("❌ No PDFs uploaded! Upload PDFs first.")
            return
        session['mode'] = 'delete_by_image'
        await query.edit_message_text("🖼️ Send screenshot/image of page to delete")
    
    elif data == 'add_watermark':
        if not session['pdfs']:
            await query.edit_message_text("❌ Upload PDFs first!")
            return
        session['mode'] = 'watermark_text'
        await query.edit_message_text("📝 Send watermark text")
    
    elif data == 'insert_page':
        if not session['pdfs']:
            await query.edit_message_text("❌ Upload PDFs first!")
            return
        session['mode'] = 'insert_page_number'
        await query.edit_message_text("📄 Send page number where to insert (e.g., 3)")
    
    elif data == 'find_replace':
        if not session['pdfs']:
            await query.edit_message_text("❌ Upload PDFs first!")
            return
        
        words = await extract_common_words(session['pdfs'])
        session['common_words'] = words
        
        word_list = "\n".join([f"{i+1}. {word} ({count})" for i, (word, count) in enumerate(words[:20])])
        
        keyboard = [[InlineKeyboardButton("Skip Suggestions", callback_data='skip_suggestions')]]
        
        await query.edit_message_text(
            f"🔍 *Most Common Words:*\n\n{word_list}\n\n"
            "Send word to find (or skip):",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        session['mode'] = 'find_word'
    
    elif data == 'skip_suggestions':
        session['mode'] = 'find_word'
        await query.edit_message_text("🔍 Send word to find:")
    
    elif data == 'rename_files':
        if not session['pdfs']:
            await query.edit_message_text("❌ Upload PDFs first!")
            return
        session['mode'] = 'rename_pattern'
        await query.edit_message_text(
            "📛 Send new name pattern:\n"
            "Use {n} for number\n"
            "Example: Document_{n}"
        )
    
    elif data == 'thumbnail_tools':
        keyboard = [
            [InlineKeyboardButton("Create Thumbnail", callback_data='create_thumb')],
            [InlineKeyboardButton("Remove Thumbnail", callback_data='remove_thumb')],
            [InlineKeyboardButton("🔙 Back", callback_data='pdf_tools')]
        ]
        await query.edit_message_text(
            "🎨 Thumbnail Operations:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data == 'create_thumb':
        if not session['pdfs']:
            await query.edit_message_text("❌ Upload PDFs first!")
            return
        session['mode'] = 'create_thumbnail'
        await query.edit_message_text("🖼️ Send square image for thumbnail")
    
    elif data == 'remove_thumb':
        if not session['pdfs']:
            await query.edit_message_text("❌ Upload PDFs first!")
            return
        await process_remove_thumbnail(query, session)
    
    elif data == 'video_tools':
        keyboard = [
            [InlineKeyboardButton("📤 Upload Videos", callback_data='upload_videos')],
            [InlineKeyboardButton("🖼️ Set Thumbnail", callback_data='set_video_thumb')],
            [InlineKeyboardButton("📝 Thumbnail + Watermark", callback_data='video_thumb_watermark')],
            [InlineKeyboardButton("🔙 Back", callback_data='back_main')]
        ]
        await query.edit_message_text(
            "🎬 *Video Tools*",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif data == 'upload_videos':
        session['mode'] = 'upload_videos'
        await query.edit_message_text("📤 Send video files")
    
    elif data == 'set_video_thumb':
        if not session['videos']:
            await query.edit_message_text("❌ Upload videos first!")
            return
        session['mode'] = 'video_thumbnail_image'
        await query.edit_message_text("🖼️ Send thumbnail image")
    
    elif data == 'video_thumb_watermark':
        if not session['videos']:
            await query.edit_message_text("❌ Upload videos first!")
            return
        session['mode'] = 'video_thumb_watermark_image'
        await query.edit_message_text("🖼️ Send thumbnail image first")
    
    elif data == 'back_main':
        await start(update, context)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    
    session = bot_instance.get_session(update.effective_user.id)
    doc = update.message.document
    
    if session['mode'] == 'upload_pdf' and doc.mime_type == 'application/pdf':
        file = await context.bot.get_file(doc.file_id)
        pdf_bytes = await file.download_as_bytearray()
        
        session['pdfs'].append({
            'name': doc.file_name,
            'data': bytes(pdf_bytes)
        })
        
        await update.message.reply_text(f"✅ Added: {doc.file_name}\n📊 Total PDFs: {len(session['pdfs'])}")
    
    elif session['mode'] == 'upload_videos' and 'video' in doc.mime_type:
        file = await context.bot.get_file(doc.file_id)
        video_bytes = await file.download_as_bytearray()
        
        session['videos'].append({
            'name': doc.file_name,
            'data': bytes(video_bytes)
        })
        
        await update.message.reply_text(f"✅ Added: {doc.file_name}\n📊 Total Videos: {len(session['videos'])}")

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    
    session = bot_instance.get_session(update.effective_user.id)
    
    if session['mode'] == 'upload_videos':
        video = update.message.video
        file = await context.bot.get_file(video.file_id)
        video_bytes = await file.download_as_bytearray()
        
        session['videos'].append({
            'name': f"video_{len(session['videos'])+1}.mp4",
            'data': bytes(video_bytes)
        })
        
        await update.message.reply_text(f"✅ Video added\n📊 Total: {len(session['videos'])}")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    
    session = bot_instance.get_session(update.effective_user.id)
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    img_bytes = await file.download_as_bytearray()
    
    if session['mode'] == 'delete_by_image':
        await process_delete_by_image(update, session, bytes(img_bytes))
    
    elif session['mode'] == 'insert_page_image':
        session['temp_data']['insert_image'] = bytes(img_bytes)
        await process_insert_page(update, session)
    
    elif session['mode'] == 'create_thumbnail':
        await process_create_thumbnail(update, session, bytes(img_bytes))
    
    elif session['mode'] == 'video_thumbnail_image':
        session['temp_data']['video_thumb'] = bytes(img_bytes)
        await process_video_thumbnails(update, session, context)
    
    elif session['mode'] == 'video_thumb_watermark_image':
        session['temp_data']['video_thumb'] = bytes(img_bytes)
        session['mode'] = 'video_watermark_text'
        await update.message.reply_text("📝 Now send watermark text")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return
    
    session = bot_instance.get_session(update.effective_user.id)
    text = update.message.text
    
    if session['mode'] == 'watermark_text':
        session['temp_data']['watermark_text'] = text
        session['mode'] = 'watermark_opacity'
        await update.message.reply_text("🎨 Send opacity (0.1 to 1.0, e.g., 0.3)")
    
    elif session['mode'] == 'watermark_opacity':
        try:
            opacity = float(text)
            if 0.1 <= opacity <= 1.0:
                await process_watermark(update, session, opacity)
            else:
                await update.message.reply_text("❌ Opacity must be between 0.1 and 1.0")
        except:
            await update.message.reply_text("❌ Invalid number!")
    
    elif session['mode'] == 'insert_page_number':
        try:
            page_num = int(text)
            session['temp_data']['insert_position'] = page_num
            session['mode'] = 'insert_page_image'
            await update.message.reply_text("📄 Now send the page image to insert")
        except:
            await update.message.reply_text("❌ Invalid page number!")
    
    elif session['mode'] == 'find_word':
        session['temp_data']['find_word'] = text
        session['mode'] = 'replace_word'
        
        keyboard = [[InlineKeyboardButton("Skip Replace", callback_data='skip_replace')]]
        await update.message.reply_text(
            f"🔍 Finding: *{text}*\n\nSend replacement word (or skip):",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    elif session['mode'] == 'replace_word':
        await process_find_replace(update, session, text)
    
    elif session['mode'] == 'rename_pattern':
        await process_rename(update, session, text)
    
    elif session['mode'] == 'video_watermark_text':
        session['temp_data']['watermark_text'] = text
        await process_video_thumbnails_with_watermark(update, session, context)

async def extract_common_words(pdfs):
    all_text = ""
    for pdf_data in pdfs:
        doc = fitz.open(stream=pdf_data['data'], filetype="pdf")
        for page in doc:
            all_text += page.get_text()
        doc.close()
    
    words = re.findall(r'\b[a-zA-Z]{3,}\b', all_text.lower())
    return Counter(words).most_common(30)

async def process_delete_by_image(update, session, img_bytes):
    await update.message.reply_text("🔍 Searching for matching pages...")
    
    target_img = cv2.imdecode(np.frombuffer(img_bytes, np.uint8), cv2.IMREAD_COLOR)
    target_gray = cv2.cvtColor(target_img, cv2.COLOR_BGR2GRAY)
    
    sift = cv2.SIFT_create()
    kp1, des1 = sift.detectAndCompute(target_gray, None)
    
    for pdf_idx, pdf_data in enumerate(session['pdfs']):
        doc = fitz.open(stream=pdf_data['data'], filetype="pdf")
        writer = PdfWriter()
        reader = PdfReader(io.BytesIO(pdf_data['data']))
        
        pages_to_keep = []
        deleted_pages = []
        
        for page_num in range(len(reader.pages)):
            pix = doc[page_num].get_pixmap(matrix=fitz.Matrix(2, 2))
            img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
            
            gray = cv2.cvtColor(img_data, cv2.COLOR_RGB2GRAY)
            kp2, des2 = sift.detectAndCompute(gray, None)
            
            if des1 is not None and des2 is not None:
                bf = cv2.BFMatcher()
                matches = bf.knnMatch(des1, des2, k=2)
                
                good_matches = []
                for m, n in matches:
                    if m.distance < 0.75 * n.distance:
                        good_matches.append(m)
                
                if len(good_matches) > 50:
                    deleted_pages.append(page_num + 1)
                else:
                    writer.add_page(reader.pages[page_num])
            else:
                writer.add_page(reader.pages[page_num])
        
        doc.close()
        
        if deleted_pages:
            output = io.BytesIO()
            writer.write(output)
            output.seek(0)
            
            await update.message.reply_document(
                document=output,
                filename=f"deleted_{pdf_data['name']}",
                caption=f"✅ Deleted pages: {deleted_pages}"
            )
        else:
            await update.message.reply_text(f"❌ No matching pages in {pdf_data['name']}")
    
    session['mode'] = None

async def process_watermark(update, session, opacity):
    await update.message.reply_text("⚙️ Adding watermarks...")
    
    watermark_text = session['temp_data']['watermark_text']
    
    for pdf_data in session['pdfs']:
        doc = fitz.open(stream=pdf_data['data'], filetype="pdf")
        
        for page in doc:
            rect = page.rect
            text_width = len(watermark_text) * 5
            
            tw = fitz.TextWriter(rect)
            tw.append(
                (rect.width/2 - text_width/2, rect.height - 20),
                watermark_text,
                fontsize=10
            )
            tw.write_text(page, color=(0.5, 0.5, 0.5), opacity=opacity)
        
        output = io.BytesIO()
        doc.save(output)
        doc.close()
        output.seek(0)
        
        await update.message.reply_document(
            document=output,
            filename=f"watermarked_{pdf_data['name']}"
        )
    
    session['mode'] = None
    await update.message.reply_text("✅ Watermarks added!")

async def process_insert_page(update, session):
    await update.message.reply_text("📄 Inserting pages...")
    
    position = session['temp_data']['insert_position']
    img_bytes = session['temp_data']['insert_image']
    
    img = Image.open(io.BytesIO(img_bytes))
    img = img.convert('RGB')
    
    img_pdf = io.BytesIO()
    img.save(img_pdf, 'PDF', resolution=100.0)
    img_pdf.seek(0)
    
    for pdf_data in session['pdfs']:
        reader = PdfReader(io.BytesIO(pdf_data['data']))
        writer = PdfWriter()
        
        img_reader = PdfReader(img_pdf)
        
        for i in range(len(reader.pages)):
            if i == position - 1:
                writer.add_page(img_reader.pages[0])
            writer.add_page(reader.pages[i])
        
        output = io.BytesIO()
        writer.write(output)
        output.seek(0)
        
        await update.message.reply_document(
            document=output,
            filename=f"inserted_{pdf_data['name']}"
        )
    
    session['mode'] = None
    await update.message.reply_text("✅ Pages inserted!")

async def process_find_replace(update, session, replace_word):
    await update.message.reply_text("🔄 Finding and replacing...")
    
    find_word = session['temp_data']['find_word']
    
    for pdf_data in session['pdfs']:
        doc = fitz.open(stream=pdf_data['data'], filetype="pdf")
        
        for page in doc:
            text_instances = page.search_for(find_word)
            
            for inst in text_instances:
                page.add_redact_annot(inst, fill=(1, 1, 1))
            page.apply_redactions()
            
            for inst in text_instances:
                page.insert_text(inst.tl, replace_word, fontsize=10)
        
        output = io.BytesIO()
        doc.save(output)
        doc.close()
        output.seek(0)
        
        await update.message.reply_document(
            document=output,
            filename=f"replaced_{pdf_data['name']}"
        )
    
    session['mode'] = None
    await update.message.reply_text("✅ Text replaced!")

async def process_rename(update, session, pattern):
    await update.message.reply_text("📛 Renaming files...")
    
    for idx, pdf_data in enumerate(session['pdfs']):
        new_name = pattern.replace('{n}', str(idx + 1))
        if not new_name.endswith('.pdf'):
            new_name += '.pdf'
        
        await update.message.reply_document(
            document=io.BytesIO(pdf_data['data']),
            filename=new_name
        )
    
    session['mode'] = None
    await update.message.reply_text("✅ Files renamed!")

async def process_create_thumbnail(update, session, img_bytes):
    await update.message.reply_text("🎨 Creating thumbnails...")
    
    img = Image.open(io.BytesIO(img_bytes))
    img = img.convert('RGB')
    img.thumbnail((256, 256), Image.Resampling.LANCZOS)
    
    thumb_pdf = io.BytesIO()
    img.save(thumb_pdf, 'PDF')
    thumb_pdf.seek(0)
    
    for pdf_data in session['pdfs']:
        doc = fitz.open(stream=pdf_data['data'], filetype="pdf")
        
        metadata = doc.metadata
        metadata['thumbnail'] = thumb_pdf.getvalue()
        doc.set_metadata(metadata)
        
        output = io.BytesIO()
        doc.save(output)
        doc.close()
        output.seek(0)
        
        await update.message.reply_document(
            document=output,
            filename=f"thumb_{pdf_data['name']}"
        )
    
    session['mode'] = None
    await update.message.reply_text("✅ Thumbnails created!")

async def process_remove_thumbnail(query, session):
    await query.edit_message_text("🗑️ Removing thumbnails...")
    
    for pdf_data in session['pdfs']:
        doc = fitz.open(stream=pdf_data['data'], filetype="pdf")
        
        metadata = doc.metadata
        if 'thumbnail' in metadata:
            del metadata['thumbnail']
        doc.set_metadata(metadata)
        
        output = io.BytesIO()
        doc.save(output)
        doc.close()
        output.seek(0)
        
        await query.message.reply_document(
            document=output,
            filename=f"no_thumb_{pdf_data['name']}"
        )
    
    session['mode'] = None

async def process_video_thumbnails(update, session, context):
    await update.message.reply_text("🎬 Processing video thumbnails...")
    
    thumb_bytes = session['temp_data']['video_thumb']
    thumb_img = Image.open(io.BytesIO(thumb_bytes))
    thumb_img = thumb_img.convert('RGB')
    
    for video_data in session['videos']:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp_in:
            tmp_in.write(video_data['data'])
            tmp_in_path = tmp_in.name
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_thumb:
            thumb_img.save(tmp_thumb.name, 'JPEG')
            tmp_thumb_path = tmp_thumb.name
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp_out:
            tmp_out_path = tmp_out.name
        
        try:
            clip = VideoFileClip(tmp_in_path)
            duration = min(2, clip.duration)
            
            thumb_clip = ImageClip(tmp_thumb_path).set_duration(duration)
            thumb_clip = thumb_clip.resize(height=clip.h)
            
            os.system(f'ffmpeg -i {tmp_in_path} -i {tmp_thumb_path} -map 0 -map 1 -c copy -disposition:v:1 attached_pic {tmp_out_path} -y')
            
            with open(tmp_out_path, 'rb') as f:
                output_bytes = f.read()
            
            await update.message.reply_video(
                video=io.BytesIO(output_bytes),
                filename=f"thumb_{video_data['name']}"
            )
            
            clip.close()
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {video_data['name']}")
        finally:
            os.unlink(tmp_in_path)
            os.unlink(tmp_thumb_path)
            if os.path.exists(tmp_out_path):
                os.unlink(tmp_out_path)
    
    session['mode'] = None
    await update.message.reply_text("✅ Video thumbnails updated!")

async def process_video_thumbnails_with_watermark(update, session, context):
    await update.message.reply_text("🎬 Processing with watermark...")
    
    thumb_bytes = session['temp_data']['video_thumb']
    watermark_text = session['temp_data']['watermark_text']
    
    thumb_img = Image.open(io.BytesIO(thumb_bytes))
    thumb_img = thumb_img.convert('RGB')
    
    with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_thumb:
        thumb_img.save(tmp_thumb.name, 'JPEG')
        tmp_thumb_path = tmp_thumb.name
    
    for video_data in session['videos']:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp_in:
            tmp_in.write(video_data['data'])
            tmp_in_path = tmp_in.name
        
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as tmp_out:
            tmp_out_path = tmp_out.name
        
        try:
            clip = VideoFileClip(tmp_in_path)
            
            txt_clip = TextClip(watermark_text, fontsize=24, color='white', 
                              font='Arial', stroke_color='black', stroke_width=1)
            txt_clip = txt_clip.set_position(('center', 'bottom')).set_duration(clip.duration)
            
            final = CompositeVideoClip([clip, txt_clip])
            final.write_videofile(tmp_out_path, codec='libx264', audio_codec='aac')
            
            os.system(f'ffmpeg -i {tmp_out_path} -i {tmp_thumb_path} -map 0 -map 1 -c copy -disposition:v:1 attached_pic {tmp_out_path}_final.mp4 -y')
            
            with open(f'{tmp_out_path}_final.mp4', 'rb') as f:
                output_bytes = f.read()
            
            await update.message.reply_video(
                video=io.BytesIO(output_bytes),
                filename=f"watermarked_{video_data['name']}"
            )
            
            clip.close()
            final.close()
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {video_data['name']}")
        finally:
            os.unlink(tmp_in_path)
            if os.path.exists(tmp_out_path):
                os.unlink(tmp_out_path)
            if os.path.exists(f'{tmp_out_path}_final.mp4'):
                os.unlink(f'{tmp_out_path}_final.mp4')
    
    os.unlink(tmp_thumb_path)
    session['mode'] = None
    await update.message.reply_text("✅ Videos processed!")

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.VIDEO, handle_video))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    app.run_polling()

if __name__ == '__main__':
    main()