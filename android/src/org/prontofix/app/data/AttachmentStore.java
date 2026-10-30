package org.prontofix.app.data;
import android.content.Context;
import android.net.Uri;
import android.database.Cursor;
import android.provider.OpenableColumns;
import java.io.*;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.UUID;
/** Copies selected ContentResolver URIs into app-private durable storage and registers metadata. */
public final class AttachmentStore {
 private AttachmentStore(){}
 public static Attachment importUri(Context ctx,String taskId,Uri uri) throws Exception {
  String name="attachment";
  try(Cursor cur=ctx.getContentResolver().query(uri,null,null,null,null)){
   if(cur!=null&&cur.moveToFirst()){int ix=cur.getColumnIndex(OpenableColumns.DISPLAY_NAME);if(ix>=0)name=cur.getString(ix);}
  }
  if(name==null||name.trim().isEmpty())name="attachment";
  String mime=ctx.getContentResolver().getType(uri);if(mime==null)mime="application/octet-stream";
  File dir=new File(ctx.getFilesDir(),"outbox/files");if(!dir.exists()&&!dir.mkdirs())throw new IOException("Cannot create private attachment folder");
  String id=UUID.randomUUID().toString();File target=new File(dir,id+".blob");
  MessageDigest digest=MessageDigest.getInstance("SHA-256");long size=0;
  try(InputStream in=ctx.getContentResolver().openInputStream(uri);OutputStream out=new FileOutputStream(target)){
   if(in==null)throw new IOException("Cannot read selected file");byte[] b=new byte[65536];int n;
   while((n=in.read(b))!=-1){out.write(b,0,n);digest.update(b,0,n);size+=n;}
  }catch(Exception e){target.delete();throw e;}
  StringBuilder hash=new StringBuilder();for(byte b:digest.digest())hash.append(String.format(Locale.US,"%02x",b&255));
  Attachment a=new Attachment(id,taskId,target.getAbsolutePath(),name,mime,size,hash.toString(),SyncRepository.WAITING,System.currentTimeMillis());
  SyncDatabase.get(ctx).attachments().insert(a);return a;
 }
}