package org.prontofix.app.data;
import android.content.Context;
import androidx.annotation.NonNull;
import androidx.work.Constraints;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.WorkManager;

/** Single named WorkManager lane for all outbox processing requests. */
public final class QueueWork {
 private static final String UNIQUE_NAME="home-master-sync-queue";
 private QueueWork(){}
 public static void request(@NonNull Context c){
  Constraints constraints=new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build();
  OneTimeWorkRequest work=new OneTimeWorkRequest.Builder(QueueDrainWorker.class).setConstraints(constraints).build();
  WorkManager.getInstance(c.getApplicationContext()).enqueueUniqueWork(UNIQUE_NAME,ExistingWorkPolicy.KEEP,work);
 }
 /** Explicit user-triggered retry replaces a failed/stalled drain. */
 public static void retry(@NonNull Context c){
  Constraints constraints=new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build();
  OneTimeWorkRequest work=new OneTimeWorkRequest.Builder(QueueDrainWorker.class).setConstraints(constraints).build();
  WorkManager.getInstance(c.getApplicationContext()).enqueueUniqueWork(UNIQUE_NAME,ExistingWorkPolicy.REPLACE,work);
 }
}
