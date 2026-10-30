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
 @Query("UPDATE sync_tasks SET status='SENDING',updatedAt=:now,lastError=NULL,attempts=attempts+1,leaseOwner=:owner WHERE id=:id AND status IN ('WAITING','RETRY')") public abstract int claim(String id,long now,String owner);
 @Query("UPDATE sync_tasks SET status=:status,updatedAt=:now,lastError=:error,leaseOwner=NULL WHERE id=:id AND leaseOwner=:owner AND status='SENDING'") public abstract int finishOwned(String id,String owner,String status,long now,String error);
 @Query("UPDATE sync_tasks SET remoteOrderId=:remoteId,status='UPLOADED',updatedAt=:now,lastError=NULL,leaseOwner=NULL WHERE id=:id AND leaseOwner=:owner AND status='SENDING'") public abstract int confirmOwned(String id,long remoteId,long now,String owner);
 @Query("UPDATE sync_tasks SET remoteOrderId=:remoteId,status='UPLOADED',updatedAt=:now,lastError=NULL WHERE id=:id") public abstract int setConfirmed(String id,long remoteId,long now);
 /** Only stale leases may be reclaimed; never reset a fresh in-flight request. */
 @Query("UPDATE sync_tasks SET status='RETRY',updatedAt=:now,lastError='Recovered expired worker lease',leaseOwner=NULL WHERE status='SENDING' AND updatedAt<:cutoff") public abstract int reclaimExpired(long cutoff,long now);
 @Query("UPDATE sync_tasks SET status='CANCELED',updatedAt=:now,lastError='Canceled locally before delivery',leaseOwner=NULL WHERE id=:id AND kind='ORDER' AND status IN ('WAITING','RETRY') AND remoteOrderId IS NULL") public abstract int cancelIfReady(String id,long now);
 @Query("DELETE FROM sync_tasks WHERE id=:id") public abstract int delete(String id);
}