package org.prontofix.app.data;
import androidx.room.Dao;
import androidx.room.Insert;
import androidx.room.OnConflictStrategy;
import androidx.room.Query;
import java.util.List;
@Dao public interface AttachmentDao {
 @Insert(onConflict=OnConflictStrategy.IGNORE) long insert(Attachment item);
 @Query("SELECT * FROM attachments WHERE taskId=:taskId ORDER BY createdAt") List<Attachment> byTask(String taskId);
 @Query("SELECT * FROM attachments WHERE status IN ('WAITING','RETRY','SENDING') ORDER BY createdAt") List<Attachment> pending();
 @Query("SELECT * FROM attachments ORDER BY createdAt DESC") List<Attachment> all();
 @Query("UPDATE attachments SET status=:status,lastError=:error,attempts=attempts+:attemptDelta WHERE id=:id") int setState(String id,String status,String error,int attemptDelta);
 /** Reserve only a ready record; competing workers cannot both own it. */
 @Query("UPDATE attachments SET status='SENDING',lastError=NULL,attempts=attempts+1 WHERE id=:id AND status IN ('WAITING','RETRY')") int claim(String id);
 @Query("UPDATE attachments SET status='UPLOADED',remoteId=:remoteId,lastError=NULL WHERE id=:id") int setUploaded(String id,String remoteId);
 @Query("UPDATE attachments SET status='CANCELED',lastError=NULL WHERE id=:id AND status NOT IN ('UPLOADED','CANCELED')") int cancel(String id);
 @Query("DELETE FROM attachments WHERE id=:id") int delete(String id);
}