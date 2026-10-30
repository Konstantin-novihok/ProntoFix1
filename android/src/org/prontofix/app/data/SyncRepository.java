package org.prontofix.app.data;
import android.content.Context;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
public final class SyncRepository {
 public static final String WAITING="WAITING",SENDING="SENDING",UPLOADED="UPLOADED",RETRY="RETRY",ERROR="ERROR",CANCELED="CANCELED";
 private static final ExecutorService IO=Executors.newSingleThreadExecutor();
 private final SyncDatabase db;
 public SyncRepository(Context c){db=SyncDatabase.get(c);}
 public void enqueueOrder(String json,String token){
  IO.execute(()->{long now=System.currentTimeMillis();db.tasks().insert(new SyncTask(UUID.randomUUID().toString(),"ORDER",json,token,WAITING,now));});
 }
 public void enqueueAttachment(Attachment item){IO.execute(()->db.attachments().insert(item));}
 public void setTaskState(String id,String state,String error,int attempts){IO.execute(()->db.tasks().setState(id,state,System.currentTimeMillis(),error,attempts));}
 public void setAttachmentState(String id,String state,String error,int attempts){IO.execute(()->db.attachments().setState(id,state,error,attempts));}
 public void cancelAttachment(String id){IO.execute(()->db.attachments().cancel(id));}
 public SyncDatabase database(){return db;}
}