# -*- coding: utf-8 -*-

import os
import subprocess
from pipes import quote
import shlex

from gi.repository import Gtk
import quodlibet
from quodlibet import qltk
from quodlibet import _
from quodlibet.plugins.songsmenu import SongsMenuPlugin
from quodlibet.qltk.data_editors import JSONBasedEditor
from quodlibet.pattern import Pattern
from quodlibet.pattern import FileFromPattern
from quodlibet.qltk.wlw import WaitLoadWindow
from quodlibet.util.path import mkdir
from quodlibet.util import connect_obj
from quodlibet.plugins import PluginConfigMixin
from quodlibet.util.json_data import JSONObject, JSONObjectDict
from quodlibet.qltk import Icons
from quodlibet.util.dprint import print_w, print_d


def create_cmd(operation, source, target):
    return shlex.split(operation.format(quote(source), quote(target)))

def on_operation_error(operation):
    dialog = Gtk.MessageDialog(
                    type=Gtk.MessageType.ERROR,
                    message_format=str(self.song_operation) +
                    ' finished with an error',
                    buttons=Gtk.ButtonsType.OK_CANCEL)
    dialog.set_title('Operation failed!')
    response = dialog.run()
    dialog.destroy()
    return response


class FileOperator(JSONObject):
    NAME = _("File Operation")
    FIELDS = {
        "name": JSONObject.Field(_("name"),
                                 _("name")),
        "target_folder": JSONObject.Field(
            _("target_folder"),
            _("The folder to put the results in")),
        "target_path_pattern": JSONObject.Field(
            _("target_path_pattern"),
            _("The target pattern. The files will formated this way and then put into target_folder. Folders can be defined here as well.")),
        "song_operation": JSONObject.Field(
            _("song_operation"),
            _("The operation on the song (e.g. mv, cp, ffmpeg)")),
        "file_operation": JSONObject.Field(
            _("file_operation"),
            _("The operation on a file which is not a song like covers (e.g. mv, cp)")),
        "additional_files": JSONObject.Field(
            _("additional_files"),
            _("file_operation will be applied on this files.")),
        "keeps_file_extension": JSONObject.Field(
            _("keeps_file_extension"),
            _("Wheather to keep the file extension of the song"))}

    def __init__(
            self,
            name,
            target_folder="",
            target_path_pattern="",
            song_operation="",
            file_operation="",
            additional_files="",
            keeps_file_extension=True):
        JSONObject.__init__(self, name)
        self.name = name
        self.target_folder = target_folder
        self.target_path_pattern = target_path_pattern
        self.song_operation = song_operation
        self.file_operation = file_operation
        self.additional_files = additional_files
        self.keeps_file_extension = keeps_file_extension

    def operate(self, songs):
        if not os.path.isdir(self.target_folder):
            dialog = Gtk.MessageDialog(
                type=Gtk.MessageType.ERROR,
                message_format=str(
                    self.target_folder) +
                ' does not exist!',
                buttons=Gtk.ButtonsType.OK)
            dialog.set_title('Target folder does not exist!')
            dialog.run()
            dialog.destroy()
            return False

        target_file_path_pattern = FileFromPattern(
            os.path.join(self.target_folder, self.target_path_pattern))
        source_folder_pattern = Pattern(u"<~dirname>")

        win = WaitLoadWindow(None, len(songs),
                             self.song_operation +
                             " %(current)d. song of %(total)d.")
        win.show()
        for song in songs:
            if win.step():
                break
            source_file_path = song["~filename"]
            target_file_path = target_file_path_pattern.format(song)
            if not self.keeps_file_extension:
                target_file_path, _ = os.path.splitext(target_file_path)

            target_folder = os.path.dirname(target_file_path)
            source_folder = os.path.join(
                self.target_folder, source_folder_pattern.format(song))

            song_command = create_cmd(
                self.song_operation, source_file_path, target_file_path)
            print_d("song_command: " + str(song_command))
            mkdir(target_folder)

            ReturnCode = subprocess.call(song_command)
            if ReturnCode <= 0:
                if on_operation_error(self.song_operation) == Gtk.ResponseType.CANCEL:
                    break

            if self.file_operation != "":
                for file_name in [
                        file_name.strip()
                        for file_name in self.additional_files.split(",")]:
                    if os.path.isfile(os.path.join(source_folder, file_name)):
                        ReturnCode = subprocess.call(
                            create_cmd(
                                self.file_operation, os.path.join(
                                    source_folder, file_name),
                                os.path.join(target_folder, file_name)))
                        if ReturnCode <= 0:
                            if on_operation_error(self.file_operation) == Gtk.ResponseType.CANCEL:
                                break

            self.delete_empty_folders(source_folder)

        win.destroy()
        return True

    def delete_empty_folders(self, folder):
        if not os.listdir(folder):
            os.rmdir(folder)
            print_d("Deleting empty folder " + folder)
            self.delete_empty_folders(os.path.dirname(folder))
        else:
            print_d("Stoping at not empty folder " + folder)


class FileOperations(SongsMenuPlugin, PluginConfigMixin):
    PLUGIN_ID = "File Operations"
    PLUGIN_NAME = "File Operations"
    PLUGIN_DESC = "File Operations"
    PLUGIN_ICON = Gtk.STOCK_INDEX
    COMS_FILE = os.path.join(
        quodlibet.get_user_dir(), 'lists', 'file_operations.json')
    commands = None
    DEFAULT_COMS = {
        FileOperator(
            'Move Music',
            u'Musik',
            u"<albumartist>/<date> <album>/<albumartist> - <album> - <~#track> - <title>",
            "cp {} {}",
            "cp {} {}",
            "cover.jpg,cover.png",
            True)}

    def __init__(self, *args, **kwargs):
        super(FileOperations, self).__init__(*args, **kwargs)
        self.com_index = None

        submenu = Gtk.Menu()
        for name, _ in self.all_commands().items():
            item = Gtk.MenuItem(label=name)
            connect_obj(item, 'activate', self.__set_pat, name)
            submenu.append(item)
        self.set_submenu(submenu)

    @classmethod
    def PluginPreferences(cls, _):
        h_box = Gtk.HBox(spacing=3)
        h_box.set_border_width(0)

        button = qltk.Button("Edit Custom Commands" + "...", Icons.EDIT)
        button.connect("clicked", cls.edit_patterns)
        h_box.pack_start(button, True, True, 0)
        h_box.show_all()
        return h_box

    def __set_pat(self, name):
        self.com_index = name

    @classmethod
    def edit_patterns(cls, _):
        win = JSONBasedEditor(
            FileOperator, cls.all_commands(),
            filename=cls.COMS_FILE, title="Edit File Operations")
        cls.commands = None
        win.show()
        return

    def plugin_songs(self, songs):
        if self.com_index:
            self.all_commands()[self.com_index].operate(songs)

    @classmethod
    def _get_saved_commands(cls):
        filename = cls.COMS_FILE
        print_d("Loading saved commands from '%s'..." % filename)
        coms = None
        try:
            with open(filename, "r") as fil:
                coms = JSONObjectDict.from_json(FileOperator, fil.read())
        except (IOError, ValueError) as exept:
            print_w("Couldn't parse saved commands (%s)" % exept)

        # Failing all else...
        if not coms:
            print_d("No commands found in %s. Using defaults." % filename)
            coms = {c.name: c for c in cls.DEFAULT_COMS}
        print_d("Loaded commands: %s" % coms.keys())
        return coms

    @classmethod
    def all_commands(cls):
        if cls.commands is None:
            cls.commands = cls._get_saved_commands()
        return cls.commands
