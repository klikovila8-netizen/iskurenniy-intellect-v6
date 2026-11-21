#!/usr/bin/env python3
# Искуренный интеллект 6.0 — controlled desktop assistant
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import threading, queue, json, os, re, base64, urllib.request, urllib.error, urllib.parse, datetime, subprocess, sys, shutil
from pathlib import Path

APP="Искуренный интеллект 6.0"
ROOT=Path(sys.executable).resolve().parent if getattr(sys,"frozen",False) else Path(__file__).resolve().parent
DATA=ROOT/"ii6_data"; DATA.mkdir(exist_ok=True)
CHATS=DATA/"chats"; CHATS.mkdir(exist_ok=True)
WORKSPACE=ROOT/"workspace"; WORKSPACE.mkdir(exist_ok=True)
CFG=DATA/"config.json"; MEMORY=DATA/"memory.txt"; ACTION_LOG=DATA/"action_log.txt"
DEFAULT={"endpoint":"https://api.openai.com/v1","model":"gpt-4o-mini",
 "personality":"Ты дружелюбный русскоязычный помощник. Отвечай понятно, по делу, с лёгким юмором.",
 "context":18,"workspace":str(WORKSPACE)}
try: config=DEFAULT|json.loads(CFG.read_text(encoding="utf8"))
except Exception: config=DEFAULT.copy()
WORKSPACE=Path(config.get("workspace",str(WORKSPACE))).expanduser().resolve()
WORKSPACE.mkdir(parents=True,exist_ok=True)

def save_config():
    CFG.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding="utf8")

def safe_path(user_path):
    """Resolve a user-supplied relative path and enforce workspace containment."""
    p=(WORKSPACE / user_path).resolve() if not Path(user_path).is_absolute() else Path(user_path).resolve()
    if p != WORKSPACE and WORKSPACE not in p.parents:
        raise ValueError("Доступ разрешён только внутри рабочей папки.")
    return p

def log_action(text):
    stamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with ACTION_LOG.open("a",encoding="utf8") as f:f.write(f"[{stamp}] {text}\n")

def preview_action(title,description):
    """Show dry-run preview. User must explicitly approve each action."""
    w=tk.Toplevel(); w.title("Предварительный просмотр — подтверждение"); w.geometry("540x330")
    w.transient(); w.grab_set()
    ttk.Label(w,text=title,font=("Segoe UI",12,"bold")).pack(anchor="w",padx=12,pady=(12,6))
    box=tk.Text(w,wrap="word",height=11); box.pack(fill="both",expand=True,padx=12,pady=6)
    box.insert("1.0",description); box.config(state="disabled")
    result={"approved":False}
    row=ttk.Frame(w); row.pack(pady=10)
    def yes():result["approved"]=True; w.destroy()
    ttk.Button(row,text="Подтвердить и выполнить",command=yes).pack(side="left",padx=6)
    ttk.Button(row,text="Отмена",command=w.destroy).pack(side="left",padx=6)
    w.wait_window()
    return result["approved"]

def extract_code(text):
    m=re.search(r"```(?:[\w+-]*)\s*\n(.*?)```",text,re.S)
    return m.group(1).strip() if m else None

def read_document(path):
    p=Path(path); ext=p.suffix.lower()
    if ext in (".txt",".md",".csv",".json",".py",".html",".xml",".log"):
        return p.read_text(encoding="utf8",errors="replace")
    if ext==".pdf":
        try:
            from pypdf import PdfReader
            return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
        except ImportError: raise RuntimeError("Для PDF установи pypdf.")
    if ext==".docx":
        try:
            from docx import Document
            return "\n".join(par.text for par in Document(path).paragraphs)
        except ImportError: raise RuntimeError("Для Word установи python-docx.")
    raise RuntimeError("Формат не поддерживается.")

def image_content(path):
    ext=Path(path).suffix.lower()
    mime={".png":"image/png",".jpg":"image/jpeg",".jpeg":"image/jpeg",".webp":"image/webp"}.get(ext)
    if not mime:raise ValueError("Поддерживаются PNG/JPG/WEBP.")
    data=base64.b64encode(Path(path).read_bytes()).decode()
    return {"type":"image_url","image_url":{"url":f"data:{mime};base64,{data}"}}

def call_api(messages,key,images=()):
    if not key:raise RuntimeError("Добавь API-ключ в Настройки.")
    payload={"model":config["model"],"messages":messages,"temperature":0.7}
    if images:
        payload["messages"][-1]["content"]=[{"type":"text","text":payload["messages"][-1]["content"]}]+[image_content(i) for i in images]
    req=urllib.request.Request(config["endpoint"].rstrip("/")+"/chat/completions",
       data=json.dumps(payload).encode(),headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req,timeout=100) as resp: data=json.loads(resp.read())
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:raise RuntimeError(f"API HTTP {e.code}: {e.read().decode(errors='replace')[:600]}")
    except urllib.error.URLError as e:raise RuntimeError("Нет соединения: "+str(e.reason))

def web_search(query):
    req=urllib.request.Request("https://html.duckduckgo.com/html/?q="+urllib.parse.quote(query),headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(req,timeout=20) as resp: page=resp.read().decode(errors="replace")
    results=[]
    for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',page,re.S):
        url,title=m.groups(); title=re.sub(r"<[^>]+>","",title)
        results.append(title.strip()+"\n"+url)
        if len(results)>=5:break
    return "\n\n".join(results) or "Поиск не вернул результатов."

class Chat:
    def __init__(self,chat_id=None,title="Новый чат",messages=None):
        self.id=chat_id or datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.title=title; self.messages=messages or []
    def save(self):
        (CHATS/(self.id+".json")).write_text(json.dumps({"id":self.id,"title":self.title,"messages":self.messages},ensure_ascii=False,indent=2),encoding="utf8")

def load_chats():
    items=[]
    for f in sorted(CHATS.glob("*.json"),reverse=True):
        try:
            d=json.loads(f.read_text(encoding="utf8")); items.append(Chat(d.get("id",f.stem),d.get("title","Чат"),d.get("messages",[])))
        except Exception:pass
    return items

class App:
 def __init__(self,root):
    self.root=root; root.title(APP); root.geometry("1150x760"); root.minsize(860,580)
    self.key=os.environ.get("OPENAI_API_KEY","")
    self.memory=MEMORY.read_text(encoding="utf8") if MEMORY.exists() else ""
    self.chats=load_chats(); self.current=None; self.queue=queue.Queue(); self.busy=False; self.attachments=[]
    self.style(); self.build()
    self.new_chat() if not self.chats else self.select_chat(self.chats[0])
    self.poll(); root.protocol("WM_DELETE_WINDOW",self.close)

 def style(self):
    st=ttk.Style()
    try:st.theme_use("clam")
    except:pass
    st.configure("TFrame",background="#17191e"); st.configure("Side.TFrame",background="#22252b")
    st.configure("TLabel",background="#17191e",foreground="#eee")
    st.configure("Side.TLabel",background="#22252b",foreground="#eee")
    st.configure("TButton",padding=6)
    st.configure("Treeview",background="#252932",foreground="white",fieldbackground="#252932",rowheight=26)

 def build(self):
    side=ttk.Frame(self.root,style="Side.TFrame",width=230); side.pack(side="left",fill="y"); side.pack_propagate(False)
    ttk.Label(side,text="🚬 ИСКУРЕННЫЙ 6.0",style="Side.TLabel",font=("Segoe UI",13,"bold")).pack(anchor="w",padx=12,pady=12)
    ttk.Button(side,text="+ Новый чат",command=self.new_chat).pack(fill="x",padx=10)
    self.chat_list=tk.Listbox(side,bg="#22252b",fg="white",selectbackground="#53657b",borderwidth=0)
    self.chat_list.pack(fill="both",expand=True,padx=8,pady=8); self.chat_list.bind("<<ListboxSelect>>",self.on_select)
    ttk.Button(side,text="Удалить чат",command=self.delete_chat).pack(fill="x",padx=10,pady=4)
    ttk.Button(side,text="🧠 Память",command=self.memory_editor).pack(fill="x",padx=10,pady=4)
    ttk.Button(side,text="⚙ Настройки",command=self.settings).pack(fill="x",padx=10,pady=4)
    ttk.Button(side,text="🛡 Журнал действий",command=self.show_log).pack(fill="x",padx=10,pady=(4,12))
    main=ttk.Frame(self.root); main.pack(side="left",fill="both",expand=True)
    top=ttk.Frame(main); top.pack(fill="x",padx=10,pady=8)
    self.chat_title=ttk.Label(top,text="Чат",font=("Segoe UI",14,"bold")); self.chat_title.pack(side="left")
    ttk.Button(top,text="Сохранить код",command=self.save_code).pack(side="right")
    self.chat_view=tk.Text(main,wrap="word",bg="#202329",fg="#f0f0f0",insertbackground="white",font=("Segoe UI",11),padx=10,pady=10,state="disabled",borderwidth=0)
    self.chat_view.pack(fill="both",expand=True,padx=10,pady=4)
    self.chat_view.tag_config("user",foreground="#8ac7ff",font=("Segoe UI",11,"bold")); self.chat_view.tag_config("ai",foreground="#9ce3a0",font=("Segoe UI",11,"bold"))
    self.input=tk.Text(main,height=4,wrap="word",bg="#292d34",fg="white",insertbackground="white",font=("Segoe UI",11),borderwidth=0)
    self.input.pack(fill="x",padx=10,pady=5); self.input.bind("<Control-Return>",lambda e:self.send())
    bar=ttk.Frame(main); bar.pack(fill="x",padx=10,pady=(0,7))
    for label,cmd in [("🎙 Диктовка",self.voice_input),("🔊 Читать",self.speak_last),("📎 Документ",self.attach_doc),("🖼 Фото",self.attach_image),("🌐 Поиск",self.search),("💻 Код",self.code_request),("Отправить",self.send)]:
        ttk.Button(bar,text=label,command=cmd).pack(side="left",padx=2)
    self.attach_label=ttk.Label(bar,text=""); self.attach_label.pack(side="right")
    actions=ttk.LabelFrame(main,text="Управление компьютером — только с подтверждением")
    actions.pack(fill="x",padx=10,pady=(0,6))
    for label,cmd in [("📂 Рабочая папка",self.open_workspace),("📝 Создать файл",self.create_file),("📖 Читать файл",self.read_workspace_file),("🗑 Удалить файл",self.delete_workspace_file),("▶ Запустить выбранное",self.launch_selected)]:
        ttk.Button(actions,text=label,command=cmd).pack(side="left",padx=3,pady=4)
    self.status=tk.StringVar(value="Готов · Ctrl+Enter отправляет сообщение")
    ttk.Label(main,textvariable=self.status,relief="sunken",anchor="w",padding=4).pack(fill="x",side="bottom")

 def refresh_list(self):
    self.chat_list.delete(0,"end")
    for c in self.chats:self.chat_list.insert("end",c.title)
    if self.current in self.chats:
        i=self.chats.index(self.current); self.chat_list.selection_set(i); self.chat_list.see(i)

 def new_chat(self):
    c=Chat(); self.chats.insert(0,c); self.current=c; self.refresh_list(); self.render(); self.chat_title.config(text=c.title); self.input.focus_set()
 def select_chat(self,c):
    self.current=c; self.refresh_list(); self.render(); self.chat_title.config(text=c.title)
 def on_select(self,event=None):
    sel=self.chat_list.curselection()
    if sel:self.select_chat(self.chats[sel[0]])
 def render(self):
    self.chat_view.config(state="normal"); self.chat_view.delete("1.0","end")
    for m in self.current.messages:
        self.chat_view.insert("end","Ты: " if m["role"]=="user" else "ИИ: ","user" if m["role"]=="user" else "ai")
        self.chat_view.insert("end",m.get("content","")+"\n\n")
    self.chat_view.config(state="disabled"); self.chat_view.see("end")
 def add_message(self,role,text):
    self.current.messages.append({"role":role,"content":text}); self.current.save(); self.render()
    if role=="user" and self.current.title=="Новый чат":
        self.current.title=text.splitlines()[0][:38]; self.chat_title.config(text=self.current.title); self.refresh_list()
 def delete_chat(self):
    if not self.current:return
    if not messagebox.askyesno("Подтверждение","Удалить текущую переписку?"):return
    try:(CHATS/(self.current.id+".json")).unlink(missing_ok=True)
    except Exception as e:messagebox.showerror("Ошибка",str(e));return
    self.chats.remove(self.current); self.new_chat() if not self.chats else self.select_chat(self.chats[0])

 def attach_doc(self):
    path=filedialog.askopenfilename(filetypes=[("Документы","*.txt *.md *.csv *.json *.py *.pdf *.docx"),("Все файлы","*.*")])
    if not path:return
    try:self.attachments.append(("text",path,read_document(path)[:25000])); self.update_attachments()
    except Exception as e:messagebox.showerror("Документ",str(e))
 def attach_image(self):
    path=filedialog.askopenfilename(filetypes=[("Изображения","*.png *.jpg *.jpeg *.webp")])
    if path:self.attachments.append(("image",path,None)); self.update_attachments()
 def update_attachments(self):self.attach_label.config(text="Вложения: "+", ".join(Path(x[1]).name for x in self.attachments))
 def send(self):
    txt=self.input.get("1.0","end").strip()
    if not txt and not self.attachments:return
    if self.busy:return
    at=self.attachments[:]; self.attachments.clear(); self.update_attachments()
    txt=txt or "Проанализируй прикреплённые файлы."
    for kind,path,content in at:
        if kind=="text":txt+=f"\n\n[Файл: {Path(path).name}]\n{content}"
    self.input.delete("1.0","end"); self.add_message("user",txt)
    self.ask(txt,[x[1] for x in at if x[0]=="image"])
 def ask(self,text,images=None,extra=None):
    if not self.key:self.add_message("assistant","ИИ не подключён: открой Настройки и введи API-ключ.");return
    self.busy=True; self.status.set("ИИ думает…")
    history=self.current.messages[-int(config.get("context",18)):]
    sysmsg=config["personality"]
    if self.memory.strip():sysmsg+="\n\nПамять (локальные заметки пользователя; используй уместно):\n"+self.memory[:10000]
    sysmsg+="\n\nТы не управляешь компьютером напрямую. Если пользователь просит действие, объясни, как сделать его через кнопки; не утверждай, что выполнил действие."
    msgs=[{"role":"system","content":sysmsg}]
    for m in history[:-1]:
        if m["role"] in ("user","assistant"):msgs.append(m)
    msgs.append({"role":"user","content":text})
    if extra:msgs.insert(1,{"role":"system","content":extra})
    def worker():
        try:self.queue.put(("answer",call_api(msgs,self.key,images or [])))
        except Exception as e:self.queue.put(("error",str(e)))
    threading.Thread(target=worker,daemon=True).start()
 def code_request(self):
    q=self.input.get("1.0","end").strip() or simpledialog.askstring("Код","Опиши программу:",parent=self.root)
    if not q:return
    self.input.delete("1.0","end"); self.add_message("user","Напиши программу: "+q)
    self.ask("Сгенерируй код, полную инструкцию и выведи код в fenced block. Задача: "+q,
             extra="Сгенерированный код не запускай. Объясни риски и зависимости.")
 def save_code(self):
    latest=next((m.get("content","") for m in reversed(self.current.messages) if m["role"]=="assistant"),"")
    code=extract_code(latest)
    if not code:messagebox.showinfo("Код","В последнем ответе нет кодового блока.");return
    ext=".py" if "```python" in latest.lower() else ".txt"
    dest=filedialog.asksaveasfilename(defaultextension=ext)
    if not dest:return
    try:
        if ext==".py":compile(code,"<saved-code>","exec")
        Path(dest).write_text(code,encoding="utf8"); log_action("Сохранён код: "+dest)
        messagebox.showinfo("Сохранено","Файл записан. Код проверен на синтаксис, автоматически не запускался.")
    except Exception as e:messagebox.showerror("Ошибка",str(e))
 def search(self):
    q=self.input.get("1.0","end").strip() or simpledialog.askstring("Поиск","Что ищем?",parent=self.root)
    if not q or self.busy:return
    self.input.delete("1.0","end"); self.add_message("user","Поиск: "+q); self.busy=True; self.status.set("Ищу в интернете…")
    def worker():
        try:self.queue.put(("search_results",(q,web_search(q))))
        except Exception as e:self.queue.put(("error","Ошибка поиска: "+str(e)))
    threading.Thread(target=worker,daemon=True).start()
 def voice_input(self):
    self.status.set("Слушаю микрофон…")
    def worker():
        try:
            import speech_recognition as sr
            r=sr.Recognizer()
            with sr.Microphone() as mic:r.adjust_for_ambient_noise(mic,duration=.5); audio=r.listen(mic,timeout=6,phrase_time_limit=30)
            self.queue.put(("voice",r.recognize_google(audio,language="ru-RU")))
        except ImportError:self.queue.put(("error","Диктовка: pip install SpeechRecognition PyAudio"))
        except Exception as e:self.queue.put(("error","Распознавание не получилось: "+str(e)))
    threading.Thread(target=worker,daemon=True).start()
 def speak_last(self):
    text=next((m.get("content","") for m in reversed(self.current.messages) if m["role"]=="assistant"),"")
    if not text:messagebox.showinfo("Озвучка","Нет ответа для чтения.");return
    text=re.sub(r"```.*?```"," (код пропущен) ",text,flags=re.S); text=re.sub(r"[#*_`>\[\]()]", "",text)[:4500]
    self.status.set("Озвучиваю…")
    def worker():
        try:
            import pyttsx3
            engine=pyttsx3.init();engine.setProperty("rate",175);engine.say(text);engine.runAndWait()
            self.queue.put(("status","Озвучивание завершено."))
        except ImportError:self.queue.put(("error","Озвучка: pip install pyttsx3"))
        except Exception as e:self.queue.put(("error","Ошибка озвучки: "+str(e)))
    threading.Thread(target=worker,daemon=True).start()
 def memory_editor(self):
    w=tk.Toplevel(self.root);w.title("Локальная память");w.geometry("560x430")
    ttk.Label(w,text="Память хранится локально в ii6_data/memory.txt. Не сохраняй секреты.",wraplength=520).pack(padx=12,pady=10)
    t=tk.Text(w,wrap="word");t.pack(fill="both",expand=True,padx=12,pady=5);t.insert("1.0",self.memory)
    def save():
        self.memory=t.get("1.0","end").strip();MEMORY.write_text(self.memory,encoding="utf8");w.destroy();messagebox.showinfo("Память","Сохранено локально.")
    ttk.Button(w,text="Сохранить",command=save).pack(pady=8)
 def settings(self):
    w=tk.Toplevel(self.root);w.title("Настройки");w.geometry("620x460")
    fields={}
    def field(label,val,secret=False):
        row=ttk.Frame(w);row.pack(fill="x",padx=12,pady=6);ttk.Label(row,text=label,width=17).pack(side="left")
        var=tk.StringVar(value=val);ttk.Entry(row,textvariable=var,show="*" if secret else "").pack(side="left",fill="x",expand=True);fields[label]=var
    field("API endpoint",config["endpoint"]);field("Модель",config["model"]);field("API key",self.key,True);field("Характер",config["personality"]);field("Рабочая папка",str(WORKSPACE))
    ttk.Label(w,text="API-ключ хранится только в памяти. Рабочая папка — область файловых действий.",wraplength=550).pack(padx=12,pady=5)
    def save():
        global WORKSPACE
        config["endpoint"]=fields["API endpoint"].get().strip() or DEFAULT["endpoint"]
        config["model"]=fields["Модель"].get().strip() or DEFAULT["model"]
        config["personality"]=fields["Характер"].get().strip() or DEFAULT["personality"]
        self.key=fields["API key"].get().strip()
        try:
            newdir=Path(fields["Рабочая папка"].get()).expanduser().resolve();newdir.mkdir(parents=True,exist_ok=True)
            config["workspace"]=str(newdir);WORKSPACE=newdir
        except Exception as e:messagebox.showerror("Папка",str(e));return
        save_config();w.destroy();messagebox.showinfo("Настройки","Сохранено. API-ключ не записывается.")
    ttk.Button(w,text="Сохранить настройки",command=save).pack(pady=10)
 def show_log(self):
    w=tk.Toplevel(self.root);w.title("Журнал действий");w.geometry("700x480")
    t=tk.Text(w,wrap="word");t.pack(fill="both",expand=True,padx=8,pady=8)
    t.insert("1.0",ACTION_LOG.read_text(encoding="utf8") if ACTION_LOG.exists() else "Пока действий нет.")
    t.config(state="disabled")

 # Controlled actions: preview and explicit approval. No shell command execution.
 def open_workspace(self):
    log_action("Открыта рабочая папка: "+str(WORKSPACE))
    try:
        if sys.platform.startswith("win"):os.startfile(str(WORKSPACE))
        elif sys.platform=="darwin":subprocess.Popen(["open",str(WORKSPACE)])
        else:subprocess.Popen(["xdg-open",str(WORKSPACE)])
    except Exception as e:messagebox.showerror("Открытие папки",str(e))
 def create_file(self):
    name=simpledialog.askstring("Создать файл","Имя/относительный путь внутри рабочей папки:",parent=self.root)
    if not name:return
    try:
        dest=safe_path(name)
        content=simpledialog.askstring("Содержимое","Введи текст файла (для многострочного лучше создать пустой файл и открыть редактор):",parent=self.root)
        if content is None:return
        dest.parent.mkdir(parents=True,exist_ok=True)
        preview=f"Путь: {dest}\nРазмер: {len(content)} символов\nОперация: запись/создание файла"
        if dest.exists():preview+="\n⚠️ Файл существует — его содержимое будет заменено."
        if not preview_action("ПРЕДВАРИТЕЛЬНЫЙ ПРОСМОТР",preview):log_action("ОТМЕНЕНО создание/перезапись "+str(dest));return
        dest.write_text(content,encoding="utf8");log_action("Создан/перезаписан файл "+str(dest))
        messagebox.showinfo("Готово","Файл записан.")
    except Exception as e:messagebox.showerror("Файловая операция",str(e))
 def read_workspace_file(self):
    name=simpledialog.askstring("Читать файл","Относительный путь в рабочей папке:",parent=self.root)
    if not name:return
    try:
        p=safe_path(name)
        if not p.is_file():raise FileNotFoundError("Это не файл или файл отсутствует.")
        if not preview_action("ПРЕДПРОСМОТР ЧТЕНИЯ",f"Будет прочитан файл:\n{p}\nОбъём: {p.stat().st_size} байт"):return
        content=p.read_text(encoding="utf8",errors="replace")[:100000]
        log_action("Прочитан файл "+str(p))
        w=tk.Toplevel(self.root);w.title(p.name);w.geometry("760x540")
        t=tk.Text(w,wrap="word");t.pack(fill="both",expand=True);t.insert("1.0",content);t.config(state="disabled")
    except Exception as e:messagebox.showerror("Чтение файла",str(e))
 def delete_workspace_file(self):
    name=simpledialog.askstring("Удалить файл","Относительный путь в рабочей папке:",parent=self.root)
    if not name:return
    try:
        p=safe_path(name)
        if not p.is_file():raise FileNotFoundError("Файл не найден (удалять папки нельзя).")
        preview=f"⚠️ УДАЛЕНИЕ БЕЗ ВОССТАНОВЛЕНИЯ\nФайл: {p}\nРазмер: {p.stat().st_size} байт"
        if not preview_action("ПРЕДПРОСМОТР УДАЛЕНИЯ",preview):log_action("ОТМЕНЕНО удаление "+str(p));return
        if not messagebox.askyesno("Последнее подтверждение","Точно удалить этот файл? Это действие необратимо."):return
        p.unlink();log_action("Удалён файл "+str(p));messagebox.showinfo("Удаление","Файл удалён.")
    except Exception as e:messagebox.showerror("Удаление",str(e))
 def launch_selected(self):
    path=filedialog.askopenfilename(title="Выбери программу/файл для запуска")
    if not path:return
    p=Path(path).resolve()
    desc=f"Запустить выбранный объект через ОС:\n{p}\n\nКомандная строка не используется. Не выбирай неизвестные файлы."
    if not preview_action("ПРЕДПРОСМОТР ЗАПУСКА",desc):log_action("ОТМЕНЕНО открытие "+str(p));return
    if not messagebox.askyesno("Подтверждение запуска","Запустить/открыть выбранный файл?"):return
    try:
        if sys.platform.startswith("win"):os.startfile(str(p))
        elif sys.platform=="darwin":subprocess.Popen(["open",str(p)])
        else:subprocess.Popen(["xdg-open",str(p)])
        log_action("Запущено/открыто выбранное приложение/файл "+str(p))
    except Exception as e:messagebox.showerror("Запуск",str(e))

 def poll(self):
    try:
     while True:
        kind,payload=self.queue.get_nowait()
        if kind=="voice":self.input.insert("end",payload);self.status.set("Речь распознана — проверь и отправь.");continue
        if kind=="status":self.status.set(payload);continue
        if kind=="search_results":
            q,res=payload;self.busy=False
            self.add_message("user","Результаты поиска для: "+q+"\n"+res)
            self.ask("Суммируй результаты, приведи ссылки, не выдумывай. Запрос: "+q+"\n\n"+res,extra="Это найденные результаты поиска; сниппеты могут быть неполными.")
            continue
        self.busy=False;self.add_message("assistant",payload);self.status.set("Готов." if kind=="answer" else "Ошибка.")
    except queue.Empty:pass
    self.root.after(150,self.poll)
 def close(self):
    save_config()
    if self.current:self.current.save()
    self.root.destroy()

def main():
    root=tk.Tk();App(root);root.mainloop()
if __name__=="__main__":main()
