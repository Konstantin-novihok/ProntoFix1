package org.prontofix.app.data;
import android.content.Context;
import androidx.annotation.NonNull;
import androidx.room.Database;
import androidx.room.Room;
import androidx.room.RoomDatabase;
import androidx.room.migration.Migration;
import androidx.sqlite.db.SupportSQLiteDatabase;
@Database(entities={SyncTask.class,Attachment.class},version=4,exportSchema=false)
public abstract class SyncDatabase extends RoomDatabase {
 private static volatile SyncDatabase INSTANCE;
 public abstract SyncTaskDao tasks();
 public abstract AttachmentDao attachments();
 public static final Migration MIGRATION_3_4=new Migration(3,4){
  @Override public void migrate(@NonNull SupportSQLiteDatabase db){db.execSQL("ALTER TABLE attachments ADD COLUMN updatedAt INTEGER NOT NULL DEFAULT 0");db.execSQL("UPDATE attachments SET updatedAt=createdAt WHERE updatedAt=0");}
 };
 public static final Migration MIGRATION_2_3=new Migration(2,3){
  @Override public void migrate(@NonNull SupportSQLiteDatabase db){db.execSQL("ALTER TABLE sync_tasks ADD COLUMN remoteOrderId INTEGER");}
 };
 public static final Migration MIGRATION_1_2=new Migration(1,2){
  @Override public void migrate(@NonNull SupportSQLiteDatabase db){
   db.execSQL("CREATE TABLE IF NOT EXISTS sync_tasks (id TEXT NOT NULL PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL, authToken TEXT, status TEXT NOT NULL, attempts INTEGER NOT NULL, createdAt INTEGER NOT NULL, updatedAt INTEGER NOT NULL, lastError TEXT)");
   db.execSQL("CREATE TABLE IF NOT EXISTS attachments (id TEXT NOT NULL PRIMARY KEY, taskId TEXT NOT NULL, localPath TEXT NOT NULL, displayName TEXT NOT NULL, mimeType TEXT NOT NULL, sizeBytes INTEGER NOT NULL, sha256 TEXT NOT NULL, status TEXT NOT NULL, attempts INTEGER NOT NULL, createdAt INTEGER NOT NULL, remoteId TEXT, lastError TEXT)");
   db.execSQL("CREATE INDEX IF NOT EXISTS index_attachments_taskId ON attachments(taskId)");
   db.execSQL("CREATE INDEX IF NOT EXISTS index_attachments_status ON attachments(status)");
  }
 };
 public static SyncDatabase get(Context c){
  if(INSTANCE==null) synchronized(SyncDatabase.class){if(INSTANCE==null) INSTANCE=Room.databaseBuilder(c.getApplicationContext(),SyncDatabase.class,"hm-sync.db").addMigrations(MIGRATION_1_2,MIGRATION_2_3,MIGRATION_3_4).build();}
  return INSTANCE;
 }
}