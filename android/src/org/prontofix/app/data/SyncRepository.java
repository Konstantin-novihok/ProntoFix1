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
  enqueueOrder(UUID.randomUUID().toString(),json,token,null);
 }
 /** Stable IDs make retrying a legacy migration idempotent. Callback runs only after Room commit. */
 public void enqueueOrder(String stableId,String json,String token,Runnable committed){
  IO.execute(()->{
   try {
    db.runInTransaction(()->{
     SyncTask found=db.tasks().get(stableId);
     if(found==null) {
      long inserted=db.tasks().insert(new SyncTask(stableId,"ORDER",json,token,WAITING,System.currentTimeMillis()));
      if(inserted < 0) throw new IllegalStateException("Task insert was ignored");
     }
     SyncTask verify=db.tasks().get(stableId);
     if(verify==null || !"ORDER".equals(verify.kind)) throw new IllegalStateException("Task ID collision");
     // Stable ID is only idempotent when the entire migration payload matches.
     if(!json.equals(verify.payload) || !sameToken(token,verify.authToken))
      throw new IllegalStateException("Stable task ID conflict: existing content differs; legacy source retained");
    });
    if(committed!=null) committed.run();
   } catch(Exception ignored) { /* Keep source record; caller may retry migration. */ }
  });
 }
 public void enqueueAttachment(Attachment item){IO.execute(()->db.attachments().insert(item));}
 public void setTaskState(String id,String state,String error,int attempts){IO.execute(()->db.tasks().setState(id,state,System.currentTimeMillis(),error,attempts));}
 public void setAttachmentState(String id,String state,String error,int attempts){IO.execute(()->db.attachments().setState(id,state,error,attempts));}
 public void cancelAttachment(String id){IO.execute(()->db.attachments().cancel(id));}
 private static boolean sameToken(String a,String b){return a==null?b==null:a.equals(b);}
 public SyncDatabase database(){return db;}
}