from pathlib import Path
from PySide6.QtWidgets import QMessageBox,QMainWindow,QApplication,QFileDialog,QMenu
from PySide6.QtCore import QStringListModel
from PySide6.QtGui import QAction,QCursor
from PySide6.QtCore import Qt,QThreadPool,QStandardPaths

import core
from tag.complete import CompleteException

import os,time
from sys import exit

VERSION = "1.0"

class MainWindow(QMainWindow):
    opened_files:list[str]
    file_list_model:QStringListModel
    thread_pool:QThreadPool

    Red     =   "red"
    Green   =   "green"
    Blue    =   "blue"
    Yellow  =   "yellow"
    Black   =   "black"

    def __init__(self) -> None:
        from ui_mainwindow import Ui_MainWindow
        QMainWindow.__init__(self)
        self.ui=Ui_MainWindow()
        self.ui.setupUi(self)

        self.opened_files=[]
        self.file_list_model=QStringListModel()
        self.ui.files_list_view.setModel(self.file_list_model)

        self.ui.output_path.setText(QStandardPaths.standardLocations(QStandardPaths.MusicLocation)[0])

        self.setup_menu()

        self.helper=core.TakiyashaHelper()
        self.helper.warning.connect(self.warning)
        self.helper.info.connect(self.info)
        self.helper.error.connect(self.error)

        self.thread_pool=QThreadPool(self)
        self.thread_pool.setMaxThreadCount(20)
    

    def log(self,message:str,color:str,type:str):
        time_str=time.strftime("%H:%M:%S", time.localtime()) 
        self.ui.message_box.append("<p><font color={color}>[{type}] </font>{time}\t:{message}</p>".format(type=type,color=color,time=time_str,message=message))

    def warning(self,message:str):
        self.log(message,self.Yellow,"警告")
    
    def error(self,message:str):
        self.log(message,self.Red,"错误")

    def info(self,message:str):
        self.log(message,self.Black,"信息")
    
    def update_model(self):
        self.file_list_model.setStringList(self.opened_files)

    def setup_menu(self):
        menu=QMenu(self)
        remove_action=QAction("删除",self)
        menu.addAction(remove_action)

        self.ui.files_list_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.ui.files_list_view.customContextMenuRequested.connect(lambda pos:menu.exec(QCursor.pos()))

        def remove_items():
            for index in self.ui.files_list_view.selectedIndexes():
                if index.isValid() and index.data() in self.opened_files:
                    self.opened_files.remove(index.data())
            self.update_model()

        remove_action.triggered.connect(remove_items)
    
    def open_files(self):
        files=QFileDialog.getOpenFileNames(
            self,
            "打开文件...",
            ".",
            "所有支持的文件 (*.qmc *.mflac *.mgg *.ncm *.uc!) ;; QQ音乐 (*.qmc *.mflac *.mgg) ;; 网易云音乐 (*.ncm *.uc!) ;;所有文件 (*.*)"
        )[0]
        
        if len(files) > 0:
            for i in files:
                if i not in self.opened_files:
                    self.opened_files.append(i)

            self.update_model()

    def open_folder(self):
        dir=QFileDialog.getExistingDirectory(
            self,
            "打开文件夹",
            "."
        )
        
        vaild_ext_name:list[str]={".mflac",".mgg",".qmc",".ncm",".uc!"}

        if len(dir) > 0:
            for root,_,file_list in os.walk(dir):
                for file in file_list:
                    path=os.path.join(root,file)
                    if path not in self.opened_files:
                        if os.path.splitext(path)[-1] in vaild_ext_name:
                            self.opened_files.append(path)
            
            self.update_model()

    def select_output_path(self):
        path=QFileDialog.getExistingDirectory(
            self,
            "选择输出路径..."
        )

        if len(path) > 0:
            self.ui.output_path.setText(path)

    def use_source_path_changed(self,state):
        if state==Qt.Checked:
            self.ui.select_output_path.setEnabled(False)
            self.ui.output_path.setEnabled(False)
        else:
            self.ui.select_output_path.setEnabled(True)
            self.ui.output_path.setEnabled(True)

    def set_ui_enabled(self,enable:bool):
        self.ui.input_group_box.setEnabled(enable)
        self.ui.output_group_box.setEnabled(enable)
        self.ui.options_group_box.setEnabled(enable)
        self.ui.start.setEnabled(enable)

    def start(self):
        if not len(self.opened_files) > 0:
            QMessageBox.warning(
                self,
                "提示",
                "请至少选择一个文件!"
            )
            return

        self.set_ui_enabled(False)
        self.ui.progressBar.setMaximum(len(self.opened_files))
        self.ui.progressBar.setValue(0)
        cnt = 0
        success_cnt = 0
        folder_list:set[str]=set()
        start_time:float=time.time()

        if self.ui.no_parallel.isChecked():
            self.thread_pool.setMaxThreadCount(1)
        else:
            self.thread_pool.setMaxThreadCount(self.ui.max_thread_count.value())

        self.info("开始解密")

        for i in self.opened_files:
            srcfilepath=Path(i)

            if self.ui.use_source_path.isChecked():
                destdirpath=srcfilepath.parent
            else:
                destdirpath=Path(self.ui.output_path.text())

            kwargs={
                'srcfilepath': srcfilepath,
                'destdirpath': destdirpath,
                'probe_only': self.ui.test_only.isChecked(),
                'with_tag': not self.ui.no_tag.isChecked(),
                'search_tag': not self.ui.avoid_searching_tag.isChecked(),
                'try_fallback':self.ui.try_fallback.isChecked(),
                'overwrite':self.ui.overwrite.isChecked()
            }

            if self.ui.open_dist_folder.isChecked():
                folder_list.add(destdirpath)        #将输出文件夹加入到集合里
        
            def task_finished(file:str,e:Exception):
                nonlocal cnt,success_cnt,start_time
                cnt=cnt+1

                if e == None or e is CompleteException:
                    success_cnt=success_cnt+1
                
                if not self.ui.test_only.isChecked():
                    if e is CompleteException:
                        self.info(f"对文件 '{file}' 运行解密成功，但获取元数据失败,信息: {str(e)}")
                    elif e is Exception:
                        self.info(f"对文件 '{file}' 运行解密失败，信息: {str(e)}")
                    else:
                        self.info(f"对文件 '{file}' 运行解密成功")

                if cnt >= self.ui.progressBar.maximum():
                    self.set_ui_enabled(True)
                    self.info(f"全部解密完成，共 {cnt} 个任务,其中 {success_cnt} 个成功,用时{int(time.time()-start_time)}秒")
                    for folder in folder_list:
                        os.startfile(folder)

                self.ui.progressBar.setValue(cnt)
                self.opened_files.remove(file)
                self.update_model()

            task:core.TakiyashaTask = core.TakiyashaTask(self.helper,file=i,**kwargs)
            task.finished.connect(task_finished)

            self.thread_pool.start(task)
        
        

    def about_qt(self):
        QApplication.aboutQt()
        pass

    def about_takiyasha_gui(self):
        QMessageBox.information(
            self,
            f"关于Takiyasha GUI",
            f"Takiyasha\n"
            f"Takiyasha -- Takiyasha 是一个用来解密多种加密音乐文件的工具。\n"
            f"License - MIT\n\n"
            f"Takiyasha GUI Version {VERSION}\n"
            f"Takiyasha GUI -- Takiyasha的一个图形界面\n"
            f"License - MIT"
        )
        pass

    def exit(self):
        QApplication.exit(0)
        pass

if __name__=="__main__":
    app:QApplication = QApplication()
    w=MainWindow()
    w.show()
    exit(app.exec())