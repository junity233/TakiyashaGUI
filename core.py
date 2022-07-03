from PySide6.QtCore import Signal,QObject,QRunnable
from pathlib import Path
import libtakiyasha
import os,typing

from tag.complete import complete_from_cloudmusic,complete_from_qqmusic

def get_encryption_name(crypter:libtakiyasha.SupportsCrypter) -> str:
    return f'{type(crypter).__name__} ({crypter.cipher.cipher_name()})'

class TakiyashaHelper(QObject):
    warning=Signal(str)
    error=Signal(str)
    info=Signal(str)

    def __init__(self):
        QObject.__init__(self)

    def probe_file(self,srcfilepath:str,probe_content:bool = True,try_fallback:bool = True)->libtakiyasha.SupportsCrypter or None:
        try:
            crypter=libtakiyasha.openfile(srcfilepath,probe_content,try_fallback=try_fallback)
        except Exception as e:
            self.error.emit(f"探测输入文件 '{srcfilepath}' 的加密类型时："
                    f"{type(e).__name__}: {e}"
                    )
            pass
        else:
            if not crypter:
                return

        if crypter.seekable():
            crypter.seek(0,0)   
        
        try:
            destfilename_ext = libtakiyasha.sniff_audio_file(crypter)
        except Exception as exc:
            self.error.emit(f"探测输入文件 '{srcfilepath}' 的输出文件格式时："
                        f"{type(exc).__name__}: {exc}"
                        )
            return
        else:
            if not destfilename_ext:
                self.warning.emit(f"输入文件 '{srcfilepath}' 的输出文件格式未知")
                destfilename_ext = 'unknown'

        if crypter.seekable():
            crypter.seek(0, 0)

        return crypter, destfilename_ext

    def decrypt(self,srcfilepath: str,
        destfilepath: str,
        crypter: libtakiyasha.SupportsCrypter,
        overwrite:bool = False
        ) -> typing.IO[bytes] or None:
        # 以排他读写模式创建输出文件

        if overwrite and os.path.exists(destfilepath):
            os.remove(destfilepath)

        try:
            destfile = open(destfilepath, 'x+b')
        except FileExistsError:  # 输出文件路径已存在时应当引发的异常
            self.error.emit(f"输出文件已存在：'{destfilepath}'")
            return
        except Exception as exc:
            self.error.emit(f"打开输出文件 '{destfilepath}' 时："
                        f"{type(exc).__name__}: {exc}"
                        )
            return

        # 确保 crypter 的指针处于开头
        if crypter.seekable():
            crypter.seek(0, 0)

        # 从 crypter 中读取（解密）数据，并写入 destfile
        try:
            destfile.write(crypter.read())
        except Exception as exc:
            # 捕获到任何异常时，关闭和删除 destfile
            self.error.emit(f"解密输入文件 '{srcfilepath}' 到 '{destfilepath}' 时："
                        f"{type(exc).__name__}: {exc}"
                        )
            destfile.close()
            os.remove(destfilepath)
            return
        finally:  # 必要的收尾措施
            crypter.close()

        # 如果流程完整地走到了这里，将 destfile 的指针置零，然后返回 destfile
        destfile.seek(0, 0)
        return destfile

    def mainflow(self,srcfilepath: Path,
                destdirpath: Path,
                probe_only: bool = False,
                with_tag: bool = True,
                search_tag: bool = True,
                try_fallback:bool = True,
                overwrite:bool = False
                ) -> None:
        # 探测加密类型、预期输出格式，获取 crypter
        probe_result = self.probe_file(srcfilepath=srcfilepath,probe_content=True,try_fallback=try_fallback)
        if probe_result:  # 有探测结果
            crypter, destfilepath_ext = probe_result
            if probe_only:  # 使用者要求仅探测不解密
                self.info.emit(f"输入文件 [{get_encryption_name(crypter)}] '{srcfilepath}',"
                        f"输出文件格式为 {destfilepath_ext.upper()}"
                        )
                return
            else:
                if crypter.seekable():
                    crypter.seek(0, 0)
                destfilepath = destdirpath / (srcfilepath.stem + '.' + destfilepath_ext)
                self.info.emit(f"输入文件 [{get_encryption_name(crypter)}] '{srcfilepath}',"
                        f"输出文件 '{destfilepath}'"
                        )
        else:  # 没有探测结果，说明文件不受支持
            self.error.emit(f"不支持输入文件 '{srcfilepath}'。"
                        f"或许你忘了启用后备算法选项?"
                        )
            return

        # 解密过程
        destfile = self.decrypt(srcfilepath, destfilepath, crypter,overwrite)
        if destfile:
            self.info.emit(f"解密完成：'{srcfilepath}' -> '{destfilepath}'")
        else:  # destfile 为 None，说明解密过程中出错
            return

        # 补充标签信息
        if with_tag:
            if destfilepath_ext == 'unknown':
                self.warning.emit(f"由于输入文件 '{srcfilepath}' 的输出文件格式未知，跳过补充标签信息和封面")
            else:
                if isinstance(crypter, libtakiyasha.NCM):
                    if complete_from_cloudmusic(
                            destfile, crypter.tagdata, crypter.coverdata, search_tag=search_tag
                    ):
                        self.info.emit(f"为输出文件 '{destfilepath}' 补充了来自网易云音乐的标签信息和封面")
                elif isinstance(crypter, (libtakiyasha.QMCv1, libtakiyasha.QMCv2)):
                    if complete_from_qqmusic(destfile, search_tag=search_tag):
                        self.info.emit(f"为输出文件 '{destfilepath}' 补充了来自 QQ 音乐的标签信息和封面")
                else:
                    self.info.emit(f"目前不支持为输出文件 '{destfilepath}' 补充标签信息和封面，请自行完成")

        destfile.close()

        return

class TakiyashaTask(QRunnable,QObject):
    kwargs:dict[str,typing.Any]
    file:str
    helper:TakiyashaHelper
    finished = Signal(str,Exception)

    def __init__(self,helper:TakiyashaHelper,file:str,**kwargs):
        QRunnable.__init__(self)
        QObject.__init__(self)
        self.kwargs=kwargs
        self.file=file
        self.helper=helper
    
    def run(self):
        try:
            self.helper.mainflow(**self.kwargs)
        except Exception as e:
            self.finished.emit(self.file,e)
        else:
            self.finished.emit(self.file,None)