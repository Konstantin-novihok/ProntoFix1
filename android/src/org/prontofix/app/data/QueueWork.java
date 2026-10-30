package org.prontofix.app.data;
import android.content.Context;
import androidx.annotation.NonNull;
import androidx.work.Constraints;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.WorkManager;
public final class QueueWork {
 private QueueWork(){}
 public static void request(@NonNull Context c){
  Constraints constraints=new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build();
  OneTimeWorkRequest work=new OneTimeWorkRequest.Builder(QueueDrainWorker.class).setConstraints(constraints).build();
  WorkManager.getInstance(c.getApplicationContext()).enqueue(work);
 }
}