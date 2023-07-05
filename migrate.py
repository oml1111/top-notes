import os
import sqlite3


def migrate(cursor):
    user_version = cursor.execute("PRAGMA user_version").fetchone()[0]

    if user_version == 0:
        cursor.execute("CREATE TABLE notes(note TEXT, detail Text, date_created TEXT)")
        cursor.execute("CREATE TABLE note_bumps(note_key INTEGER, date TEXT, score INTEGER)")
        # cursor.execute("ALTER TABLE notes ADD COLUMN date_created TEXT")
        # cursor.execute("UPDATE notes SET date_created = datetime('now', 'localtime')")
        # cursor.execute("ALTER TABLE note_bumps ADD COLUMN score INTEGER DEFAULT(1)")
        cursor.execute("PRAGMA user_version = 1")
        cursor.connection.commit()
        user_version = 1

    if user_version == 1:
        cursor.execute("ALTER TABLE notes ADD COLUMN category TEXT DEFAULT('')")
        cursor.execute("PRAGMA user_version = 2")
        cursor.connection.commit()
        user_version = 2
