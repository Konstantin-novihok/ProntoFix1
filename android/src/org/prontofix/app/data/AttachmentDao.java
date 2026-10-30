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
 @Query("UPDATE attachments SET status='CANCELED',lastError=NULL WHERE id=:id AND status NOT IN ('UPLOADED','CANCELED')") int cancel(String id);
 @Query("DELETE FROM attachments WHERE id=:id") int delete(String id);
}