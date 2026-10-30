package org.prontofix.app.data;
import androidx.room.Dao;
import androidx.room.Insert;
import androidx.room.OnConflictStrategy;
import androidx.room.Query;
import androidx.room.Transaction;
import java.util.List;
@Dao public abstract class SyncTaskDao {
 @Insert(onConflict=OnConflictStrategy.IGNORE) public abstract long insert(SyncTask task);
 @Query("SELECT * FROM sync_tasks WHERE id=:id LIMIT 1") public abstract SyncTask get(String id);
 @Query("SELECT * FROM sync_tasks ORDER BY createdAt ASC") public abstract List<SyncTask> all();
 @Query("SELECT * FROM sync_tasks WHERE status IN ('WAITING','RETRY','SENDING') ORDER BY createdAt ASC") public abstract List<SyncTask> pending();
 @Query("UPDATE sync_tasks SET status=:status,updatedAt=:now,lastError=:error,attempts=attempts+:attemptDelta WHERE id=:id") public abstract int setState(String id,String status,long now,String error,int attemptDelta);
 /** Compare-and-set reservation prevents duplicate delivery by overlapping workers. */
 @Query("UPDATE sync_tasks SET status='SENDING',updatedAt=:now,lastError=NULL,attempts=attempts+1 WHERE id=:id AND status IN ('WAITING','RETRY')") public abstract int claim(String id,long now);
 @Query("UPDATE sync_tasks SET remoteOrderId=:remoteId,status='UPLOADED',updatedAt=:now,lastError=NULL WHERE id=:id") public abstract int setConfirmed(String id,long remoteId,long now);
 @Query("DELETE FROM sync_tasks WHERE id=:id") public abstract int delete(String id);
}