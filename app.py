"""Windows offline dual-directory patcher."""
import os,queue,threading,traceback,sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from sources import RomSource
from configs import discover
from patcher import patch,VERSION
from rom_io import restore

class App:
    def __init__(self,root):
        self.root=root;self.busy=False;self.events=queue.Queue();self.last=None
        root.title('MIO OriginOS 亮度 / HDR 内置 PATCH '+VERSION);root.geometry('960x650')
        self.paths=[tk.StringVar(),tk.StringVar()];self.panel=tk.StringVar(value='自动（相同映射）')
        self.hbm=tk.StringVar(value='4 万进入即峰值 / 2 万退出')
        self.sensor=tk.StringVar(value='修复已支持的 sensorservice_ex')
        self.cil=tk.StringVar(value='编译并更新策略')
        box=ttk.Frame(root,padding=18);box.pack(fill='both',expand=True);box.columnconfigure(1,weight=1)
        for row,label in enumerate(('需要修改的移植 OriginOS 解包','实际硬件的官方 ColorOS 16 解包')):
            ttk.Label(box,text=label).grid(row=row,column=0,sticky='w',pady=10)
            ttk.Entry(box,textvariable=self.paths[row]).grid(row=row,column=1,sticky='ew',padx=10)
            ttk.Button(box,text='选择目录',command=lambda n=row:self.pick(n)).grid(row=row,column=2)
        ttk.Label(box,text='面板').grid(row=2,column=0,sticky='w',pady=8)
        self.panels=ttk.Combobox(box,textvariable=self.panel,state='readonly',values=[self.panel.get()]);self.panels.grid(row=2,column=1,sticky='ew',padx=10)
        ttk.Label(box,text='HBM 策略').grid(row=3,column=0,sticky='w',pady=8)
        ttk.Combobox(box,textvariable=self.hbm,state='readonly',values=['4 万进入即峰值 / 2 万退出','ColorOS 官方分档']).grid(row=3,column=1,sticky='ew',padx=10)
        ttk.Label(box,text='传感器链路').grid(row=4,column=0,sticky='w',pady=6)
        ttk.Combobox(box,textvariable=self.sensor,state='readonly',values=['修复已支持的 sensorservice_ex','保留目标原生传感器链路']).grid(row=4,column=1,sticky='ew',padx=10)
        ttk.Label(box,text='SELinux').grid(row=5,column=0,sticky='w',pady=6)
        ttk.Combobox(box,textvariable=self.cil,state='readonly',values=['编译并更新策略','只导出需添加的 CIL 规则']).grid(row=5,column=1,sticky='ew',padx=10)
        ttk.Label(box,text='PATCH 将直接修改第一份解包，自动备份在其同级目录，并更新打包权限/标签。\n目标需已完成本机 vendor/odm 与内核亮度节点的基础适配；属性值会导出供参考。',wraplength=890).grid(row=6,column=0,columnspan=3,sticky='w',pady=12)
        buttons=ttk.Frame(box);buttons.grid(row=7,column=0,columnspan=3,sticky='w')
        self.scan=ttk.Button(buttons,text='扫描面板',command=self.analyze);self.scan.pack(side='left',padx=4)
        self.go=ttk.Button(buttons,text='PATCH',command=self.run_patch);self.go.pack(side='left',padx=4)
        self.rollback=ttk.Button(buttons,text='恢复一次 PATCH',command=self.run_restore);self.rollback.pack(side='left',padx=4)
        ttk.Button(buttons,text='打开最近备份',command=self.open_last).pack(side='left',padx=4)
        self.log=tk.Text(box,state='disabled',wrap='word',height=21);self.log.grid(row=8,column=0,columnspan=3,sticky='nsew',pady=12);box.rowconfigure(8,weight=1)
        self.write('选择两份解包，然后点击 PATCH。支持 system/system 双层路径。')
        root.protocol('WM_DELETE_WINDOW',self.close);root.after(100,self.drain)
    def pick(self,i):
        if self.busy:return
        value=filedialog.askdirectory()
        if value:self.paths[i].set(value);self.panel.set('自动（相同映射）')
    def write(self,text):
        self.log.configure(state='normal');self.log.insert('end',text+'\n');self.log.see('end');self.log.configure(state='disabled')
    def launch(self,work):
        if self.busy:return
        self.busy=True
        for b in (self.scan,self.go,self.rollback):b.configure(state='disabled')
        def run():
            try:work()
            except Exception as ex:self.events.put(('error',str(ex)));self.events.put(('log',traceback.format_exc()))
            finally:self.events.put(('done',None))
        threading.Thread(target=run,daemon=False).start()
    def analyze(self):
        path=self.paths[1].get()
        def work():
            with RomSource(path) as source:
                panels,_,cwb=discover(source)
                self.events.put(('panels',[p.name for p in panels]))
                for p in panels:self.events.put(('log',f'{p.name}：普通 {p.normal} / 峰值 {p.maximum}'))
                for c in cwb:self.events.put(('log',f'CWB {c["rect"]}，原生尺寸 {c["native_resolution"]}；配置留入本次参考目录。'))
        self.launch(work)
    def run_patch(self):
        origin,donor=[v.get() for v in self.paths]
        if not origin or not donor:messagebox.showerror('路径未选择','请选择两份 ROM 解包。');return
        choice=self.panel.get();hbm='official' if self.hbm.get().startswith('ColorOS') else 'full40k'
        sensor_mode='preserve' if self.sensor.get().startswith('保留') else 'patch'
        cil_mode='rules-only' if self.cil.get().startswith('只') else 'compile'
        def work():
            session,report=patch(origin,donor,None if choice.startswith('自动') else choice,hbm,lambda s:self.events.put(('log',s)),sensor_mode,cil_mode)
            self.events.put(('complete',(str(session),report['changed_partitions'])))
        self.launch(work)
    def run_restore(self):
        if self.busy:return
        selected=filedialog.askopenfilename(title='选择备份里的 TRANSACTION.json',filetypes=[('PATCH 记录','TRANSACTION.json')])
        if selected:self.launch(lambda:restore(Path(selected).parent,lambda s:self.events.put(('log',s))))
    def open_last(self):
        if self.last and Path(self.last).is_dir():os.startfile(self.last)
    def close(self):
        if self.busy:messagebox.showinfo('正在处理','请等待当前 PATCH / 回退完成后关闭窗口。')
        else:self.root.destroy()
    def drain(self):
        while not self.events.empty():
            kind,value=self.events.get_nowait()
            if kind=='log':self.write(value)
            elif kind=='error':self.write('未完成：'+value);messagebox.showerror('PATCH 未完成',value)
            elif kind=='panels':self.panels.configure(values=['自动（相同映射）']+value)
            elif kind=='complete':
                self.last,parts=value;messagebox.showinfo('PATCH 完成','需要重新打包：'+', '.join(parts)+'\n备份与报告：'+self.last)
            elif kind=='done':
                self.busy=False
                for b in (self.scan,self.go,self.rollback):b.configure(state='normal')
        self.root.after(100,self.drain)

if __name__=='__main__':
    if '--smoke' in sys.argv:
        root=tk.Tk();a=App(root);root.update();root.destroy()
    elif len(sys.argv)>1:
        from patcher import main
        main()
    else:
        root=tk.Tk();a=App(root);root.mainloop()
