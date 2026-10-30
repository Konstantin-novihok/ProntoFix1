package org.prontofix.app;
import android.app.job.JobParameters;
import android.app.job.JobService;

/**
 * Retired legacy scheduler entry point.
 * Queue delivery is exclusively owned by WorkManager QueueDrainWorker.
 * Keeping this component inert prevents concurrent sends from SharedPreferences.
 */
@Deprecated
public final class OrderSyncJobService extends JobService {
 @Override public boolean onStartJob(JobParameters params) {
  jobFinished(params, false);
  return false;
 }
 @Override public boolean onStopJob(JobParameters params) { return false; }
}
