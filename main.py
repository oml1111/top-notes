#!venv\Scripts\pythonw.exe

import os
import sqlite3
from collections import namedtuple
from PyQt5 import uic
from PyQt5.QtWidgets import QApplication, QDialog, QMainWindow, QMessageBox
from PyQt5.QtCore import QAbstractTableModel, Qt, QVariant
from PyQt5.QtMultimedia import QSoundEffect

from migrate import migrate

application: QApplication = None


class NoteTableModel(QAbstractTableModel):
    def __init__(self, cursor):
        super().__init__()
        self.db_cursor = cursor
        self.headers = ['Note', 'Date Created', 'Bumps']
        self.content = []
        self.selected_category = '<all>'
        self.fetch_data()

    NoteData = namedtuple('NoteData', ['note', 'date_created', 'bump_count', 'detail', 'category', 'rowid'])

    def fetch_data(self):
        self.content = cur.execute("""
            WITH bump_counts AS (
                SELECT note_key,
                       SUM(score) as bump_score
                FROM note_bumps
                GROUP BY 1
            )
            SELECT notes.note,
                   notes.date_created,
                   COALESCE(bump_counts.bump_score, 0) as bump_count,
                   notes.detail,
                   notes.category,
                   notes.rowid
            FROM notes
            LEFT JOIN bump_counts
            ON bump_counts.note_key = notes.rowid
            {category_condition}
        """.format(
            category_condition="" if self.selected_category == '<all>'else "WHERE notes.category = ?"
        ),
            tuple() if self.selected_category == '<all>' else (self.selected_category,)
        ).fetchall()

    def change_category(self, category):
        self.selected_category = category
        self.update()

    def update_row(self, row_pos, new_note, new_detail, new_category):
        row = NoteTableModel.NoteData(*self.content[row_pos])
        self.db_cursor.execute("UPDATE notes SET note=?, detail=?, category=? WHERE rowid=?", (new_note, new_detail, new_category, row.rowid))
        self.db_cursor.connection.commit()
        new_row = row._replace(note=new_note, detail=new_detail, category=new_category)
        if self.selected_category == '<all>' or self.selected_category == new_category:
            self.content[row_pos] = list(new_row)
        else:
            self.content.pop(row_pos)
        self.layoutChanged.emit()

    def delete_row(self, row_pos):
        row = NoteTableModel.NoteData(*self.content[row_pos])
        self.db_cursor.execute("DELETE FROM notes WHERE rowid=?", (row.rowid,))
        self.db_cursor.execute("DELETE FROM note_bumps WHERE note_key=?", (row.rowid,))
        self.db_cursor.connection.commit()
        self.content.pop(row_pos)
        self.layoutChanged.emit()

    def add_row(self, note, detail, category):
        self.db_cursor.execute("""
            INSERT INTO notes VALUES(?, ?, datetime('now', 'localtime'), ?)
        """, (note, detail, category))
        self.db_cursor.connection.commit()
        self.update()

    def bump(self, row_pos, direction):
        row = NoteTableModel.NoteData(*self.content[row_pos])
        self.db_cursor.execute("INSERT INTO note_bumps VALUES(?, datetime('now', 'localtime'), ?)", (row.rowid, direction))
        self.db_cursor.connection.commit()
        new_row = row._replace(bump_count=row.bump_count + direction)
        self.content[row_pos] = list(new_row)
        self.layoutChanged.emit()

    def update(self):
        self.fetch_data()
        self.layoutChanged.emit()

    def rowCount(self, parent):
        # How many rows are there?
        return len(self.content)

    def columnCount(self, parent):
        # How many columns?
        return len(self.headers)

    def data(self, index, role):
        if role != Qt.ItemDataRole.DisplayRole:
            return QVariant()
        # What's the value of the cell at the given index?
        return self.content[index.row()][index.column()]

    def headerData(self, section, orientation, role):
        if role != Qt.ItemDataRole.DisplayRole or orientation != Qt.Orientation.Horizontal:
            return QVariant()
        # What's the header for the given column?
        return self.headers[section]

    def sort(self, column, order):
        self.content.sort(key=lambda x: x[column], reverse=(order == Qt.DescendingOrder))
        self.layoutChanged.emit()


class NewNoteDialog(QDialog):
    def __init__(self, cursor, note_table_model):
        super().__init__()
        self.db_cursor: sqlite3.Cursor = cursor
        self.note_table_model: NoteTableModel = note_table_model
        uic.loadUi('new-note.ui', self)
        self.accepted.connect(self.handle_data)

    def handle_data(self):
        note = self.noteEdit.toPlainText()
        detail = self.detailEdit.toHtml()
        category = self.categoryEdit.text()
        self.note_table_model.add_row(note, detail, category)


class MainWindow(QMainWindow):
    def __init__(self, cursor):
        super().__init__()
        self.db_cursor = cursor
        uic.loadUi('main-window.ui', self)
        self.note_table_model = NoteTableModel(cursor)
        self.selected_row = -1

        self.noteTableView.setModel(self.note_table_model)
        self.noteTableView.selectionModel().currentRowChanged.connect(self.row_changed)
        self.noteTableView.setColumnWidth(0, 350)
        self.noteTableView.setColumnWidth(1, 150)
        self.noteTableView.setColumnWidth(2, 60)
        self.noteTableView.resizeRowsToContents()

        self.update_category_list()

        self.noteCreateButton.clicked.connect(self.new_note)
        self.noteDeleteButton.clicked.connect(self.delete_note)
        self.noteBumpUpButton.clicked.connect(self.bump_up)
        self.noteBumpDownButton.clicked.connect(self.bump_down)
        self.noteUpdateButton.clicked.connect(self.update_note)
        self.categorySelect.currentTextChanged.connect(self.change_category)

    def update_category_list(self):
        categories = [x[0] for x in self.db_cursor.execute("SELECT DISTINCT category FROM notes WHERE category != ''").fetchall()]
        categories.insert(0, '<all>')
        self.categorySelect.clear()
        self.categorySelect.addItems(categories)

    def change_category(self, category):
        self.note_table_model.change_category(category)
        self.noteTableView.resizeRowsToContents()

        if self.selected_row < len(self.note_table_model.content):  # Update the note browser content after category change
            row = NoteTableModel.NoteData(*self.note_table_model.content[self.selected_row])
            self.noteBrowser.setPlainText(row.note)
            self.detailBrowser.setHtml(row.detail)
            self.categoryField.setText(row.category)

    def update_note(self, signal):
        if self.selected_row < 0 or self.selected_row >= len(self.note_table_model.content):
            return
        note = self.noteBrowser.toPlainText()
        detail = self.detailBrowser.toHtml()
        category = self.categoryField.text()
        self.note_table_model.update_row(self.selected_row, note, detail, category)
        self.noteTableView.resizeRowsToContents()
        self.update_category_list()

    def bump_up(self, signal):
        if self.selected_row < 0 or self.selected_row >= len(self.note_table_model.content):
            return
        self.note_table_model.bump(self.selected_row, 1)

    def bump_down(self, signal):
        if self.selected_row < 0 or self.selected_row >= len(self.note_table_model.content):
            return
        self.note_table_model.bump(self.selected_row, -1)

    def new_note(self, signal):
        new_note_dialog = NewNoteDialog(self.db_cursor, self.note_table_model)
        new_note_dialog.exec()
        self.noteTableView.resizeRowsToContents()
        self.update_category_list()

    def delete_note(self, signal):
        if self.selected_row < 0 or self.selected_row >= len(self.note_table_model.content):
            return

        if application.keyboardModifiers() == Qt.ControlModifier:
            confirmation_received = QMessageBox.Yes
        else:
            confirmation_received = QMessageBox.question(
                self,
                '',
                'Are you sure you want to delete this row? (Hold Ctrl for quick delete)',
                QMessageBox.Yes | QMessageBox.No
            )
        if confirmation_received == QMessageBox.Yes:
            self.note_table_model.delete_row(self.selected_row)
            if self.selected_row < len(self.note_table_model.content):  # Update the note browser content after deletion
                row = NoteTableModel.NoteData(*self.note_table_model.content[self.selected_row])
                self.noteBrowser.setPlainText(row.note)
                self.detailBrowser.setHtml(row.detail)
                self.categoryField.setText(row.category)

            self.update_category_list()

    def row_changed(self, current, previous):
        row = NoteTableModel.NoteData(*self.note_table_model.content[current.row()])
        self.noteBrowser.setPlainText(row.note)
        self.detailBrowser.setHtml(row.detail)
        self.categoryField.setText(row.category)
        self.selected_row = current.row()


if __name__ == '__main__':
    user_dir = os.path.expanduser(os.path.join("~", "Documents", "top-notes"))
    os.makedirs(user_dir, exist_ok=True)

    connection = sqlite3.connect(os.path.join(user_dir, 'notes.db'))
    cur = connection.cursor()

    migrate(cur)

    application = QApplication([])
    window = MainWindow(cur)

    window.show()
    application.exec()

    cur.close()
    connection.close()
