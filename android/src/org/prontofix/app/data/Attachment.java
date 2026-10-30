package org.prontofix.app.data;
import androidx.annotation.NonNull;
import androidx.room.Entity;
import androidx.room.Index;
import androidx.room.PrimaryKey;
@Entity(tableName="attachments",indices={@Index("taskId"),@Index("status")})
public class Attachment {
 @PrimaryKey @NonNull public String id;
 @NonNull public String taskId;
 @NonNull public String localPath;
 @NonNull public String displayName;
 @NonNull public String mimeType;
 public long sizeBytes;
 @NonNull public String sha256;
 @NonNull public String status;
 public int attempts;
 public long createdAt;
 public long updatedAt;
 public String remoteId;
 public String lastError;
 public Attachment(){id="";taskId="";localPath="";displayName="";mimeType="application/octet-stream";sizeBytes=0;sha256="";status="WAITING";attempts=0;createdAt=0;}
 public Attachment(@NonNull String id,@NonNull String taskId,@NonNull String localPath,@NonNull String displayName,@NonNull String mimeType,long sizeBytes,@NonNull String sha256,@NonNull String status,long createdAt){this.id=id;this.taskId=taskId;this.localPath=localPath;this.displayName=displayName;this.mimeType=mimeType;this.sizeBytes=sizeBytes;this.sha256=sha256;this.status=status;this.createdAt=createdAt;this.updatedAt=createdAt;this.attempts=0;}
}