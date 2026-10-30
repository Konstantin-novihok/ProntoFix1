package org.prontofix.app.data;
import androidx.annotation.NonNull;
import androidx.room.Entity;
import androidx.room.PrimaryKey;
@Entity(tableName="sync_tasks")
public class SyncTask {
 @PrimaryKey @NonNull public String id;
 @NonNull public String kind;
 @NonNull public String payload;
 public String authToken;
 @NonNull public String status;
 public int attempts;
 public long createdAt;
 public long updatedAt;
 public String lastError;
 public Long remoteOrderId;
 public String leaseOwner;
 /** Room's entity constructor. */
 public SyncTask(){id="";kind="ORDER";payload="";status="WAITING";attempts=0;createdAt=0;updatedAt=0;}
 public SyncTask(@NonNull String id,@NonNull String kind,@NonNull String payload,String authToken,@NonNull String status,long now){this.id=id;this.kind=kind;this.payload=payload;this.authToken=authToken;this.status=status;this.createdAt=now;this.updatedAt=now;this.attempts=0;}
}