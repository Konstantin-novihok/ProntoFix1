package org.prontofix.app.data;
import android.content.Context;
import androidx.annotation.NonNull;
import androidx.work.Worker;
import androidx.work.WorkerParameters;
/** Queue processor entry point. Transport is intentionally not acknowledged without server confirmation. */
public final class QueueDrainWorker extends Worker {
 public QueueDrainWorker(@NonNull Context c,@NonNull WorkerParameters p){super(c,p);}
 @NonNull @Override public Result doWork(){
  try {
   SyncDatabase db=SyncDatabase.get(getApplicationContext());
   boolean pending=!db.tasks().pending().isEmpty() || !db.attachments().pending().isEmpty();
   return pending ? Result.retry() : Result.success();
  } catch(Exception ex){return Result.retry();}
 }
}