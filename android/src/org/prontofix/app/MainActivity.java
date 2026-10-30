package org.prontofix.app;

import android.Manifest;
import android.app.Activity;
import android.app.job.JobInfo;
import android.app.job.JobScheduler;
import android.content.ComponentName;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.util.Base64;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.webkit.GeolocationPermissions;
import android.webkit.JavascriptInterface;
import android.webkit.MimeTypeMap;
import android.webkit.PermissionRequest;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.List;

/**
 * Home Master / ProntoFix — Android-оболочка (Android 5.0+).
 *
 * Приложение открывает веб-интерфейс вашего сервера (https://сервер/app/) во встроенном WebView и даёт ему то,
 * чего нет у обычной страницы:
 *   • выбор файлов из ЛЮБОГО места устройства (внутренняя память, SD-карта, Google Диск...) — onShowFileChooser;
 *   • сохранение отчётов и файлов с выбором папки/носителя — системное окно «Сохранить как…» (AndroidBridge.save*);
 *   • камера и геолокация (запрос разрешений во время работы);
 *   • экран не гаснет, пока включён трекинг (AndroidBridge.keepScreenOn);
 *   • звонки (tel:), навигация (geo:, Google Maps) и внешние ссылки открываются системными приложениями.
 * Весь интерфейс и логика живут на сервере: обновили сервер — обновилось приложение у всех.
 */
public class MainActivity extends Activity {
    private static final int REQ_FILE = 1, REQ_SAVE = 2, REQ_PERM_LOC = 3, REQ_PERM_CAM = 4;
    private static final String PREFS = "cfg", KEY_SERVER = "server";

    private WebView web;
    private FrameLayout root;
    private String server = "";

    // ожидающие операции
    private ValueCallback<Uri[]> fileCallback;
    private GeolocationPermissions.Callback geoCallback;
    private String geoOrigin;
    private PermissionRequest camRequest;
    private byte[] pendingBytes;
    private String pendingUrl, pendingName, pendingMime;
    private AlertDialog serverDialog;

    // ───────────── запуск ─────────────
    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        root = new FrameLayout(this);
        setContentView(root);
        SharedPreferences sp = getSharedPreferences(PREFS, MODE_PRIVATE);
        server = sp.getString(KEY_SERVER, "");
        migrateLegacyOutbox(sp);
        buildWebView();
        if (b == null || web.restoreState(b) == null) {      // обычный запуск (или состояние не удалось восстановить)
            if (server.length() == 0) showServerDialog(false); else web.loadUrl(server + "/app/");
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        if (web != null) web.saveState(out);
    }

    private void buildWebView() {
        web = new WebView(this);
        root.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setGeolocationEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setAllowFileAccess(false);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        if (Build.VERSION.SDK_INT >= 21) s.setMixedContentMode(WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE);
        s.setUserAgentString(s.getUserAgentString() + " HomeMasterApp/2.0");
        web.addJavascriptInterface(new Bridge(), "AndroidBridge");
        web.setWebViewClient(new Client());
        web.setWebChromeClient(new Chrome());
        // скачивание по ссылке (<a download>) → тот же диалог «Сохранить как…»
        web.setDownloadListener(new android.webkit.DownloadListener() {
            @Override
            public void onDownloadStart(String url, String ua, String disp, String mime, long len) {
                if (url == null || !url.startsWith("http")) return;
                String name = android.webkit.URLUtil.guessFileName(url, disp, mime);
                saveFromUrl(url, name, mime);
            }
        });
    }

    // ───────────── выбор сервера ─────────────
    private String normalizeServer(String in) {
        String s = in == null ? "" : in.trim();
        if (s.length() == 0) return "";
        if (!s.matches("^[a-zA-Z][a-zA-Z0-9+.-]*://.*")) s = "https://" + s;
        while (s.endsWith("/")) s = s.substring(0, s.length() - 1);
        if (s.endsWith("/app")) s = s.substring(0, s.length() - 4);
        Uri u = Uri.parse(s);
        if (u.getHost() == null || !("http".equals(u.getScheme()) || "https".equals(u.getScheme()))) return "";
        return s;
    }

    private void showServerDialog(final boolean cancelable) {
        if (serverDialog != null && serverDialog.isShowing()) return;
        final EditText input = new EditText(this);
        input.setSingleLine(true);
        input.setHint("https://service.example.com");
        input.setText(server.length() > 0 ? server : "https://");
        input.setSelection(input.getText().length());
        input.setInputType(android.text.InputType.TYPE_TEXT_VARIATION_URI | android.text.InputType.TYPE_CLASS_TEXT);
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (20 * getResources().getDisplayMetrics().density);
        box.setPadding(pad, pad / 2, pad, 0);
        TextView hint = new TextView(this);
        hint.setText("Адрес вашего сервера
Server address

https://… (для интернета)  /  http://192.168.x.x:8000 (домашняя сеть)");
        box.addView(hint);
        box.addView(input);
        AlertDialog.Builder bld = new AlertDialog.Builder(this).setTitle("Home Master").setView(box).setCancelable(cancelable)
            .setPositiveButton("OK", new DialogInterface.OnClickListener() {
                @Override public void onClick(DialogInterface d, int w) {
                    String s = normalizeServer(input.getText().toString());
                    if (s.length() == 0) { Toast.makeText(MainActivity.this, "Неверный адрес / Invalid address", Toast.LENGTH_LONG).show(); showServerDialog(cancelable); return; }
                    server = s;
                    getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(KEY_SERVER, s).commit();
                    web.loadUrl(s + "/app/");
                }
            });
        if (cancelable) bld.setNegativeButton("Отмена / Cancel", null);
        serverDialog = bld.create();
        serverDialog.show();
    }

    private boolean isInternal(Uri u) {
        Uri base = Uri.parse(server);
        return base.getHost() != null && base.getHost().equalsIgnoreCase(u.getHost()) && base.getPort() == u.getPort();
    }

    // ───────────── переходы по ссылкам и ошибки загрузки ─────────────
    private class Client extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView v, String url) {
            Uri u = Uri.parse(url);
            String sch = u.getScheme() == null ? "" : u.getScheme();
            if (sch.equals("hm-retry")) { web.loadUrl(server + "/app/"); return true; }
            if (sch.equals("hm-server")) { showServerDialog(true); return true; }
            if ((sch.equals("http") || sch.equals("https")) && isInternal(u)) return false;
            try {                                                // tel:, geo:, mailto:, sms:, внешние http(s) (Google Maps и т.п.)
                startActivity(new Intent(Intent.ACTION_VIEW, u));
            } catch (ActivityNotFoundException e) {
                Toast.makeText(MainActivity.this, url, Toast.LENGTH_SHORT).show();
            }
            return true;
        }

        private void showError(WebView v, String msg) {
            String html = "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head>"
                + "<body style='font-family:sans-serif;padding:28px;text-align:center'>"
                + "<h2>Нет связи с сервером<br><small style='font-weight:normal'>Cannot reach the server</small></h2>"
                + "<p style='color:#666'>" + server.replace("<", "") + "<br>" + msg.replace("<", "") + "</p>"
                + "<p><a href='hm-retry://go' style='font-size:20px'>↻ Повторить / Retry</a></p>"
                + "<p><a href='hm-server://change' style='font-size:18px'>⚙ Сменить сервер / Change server</a></p></body></html>";
            v.loadDataWithBaseURL(null, html, "text/html", "utf-8", null);
        }

        @Override
        public void onReceivedError(WebView v, WebResourceRequest r, WebResourceError e) {          // API 23+
            if (r.isForMainFrame()) showError(v, String.valueOf(e.getDescription()));
        }

        @Override
        @SuppressWarnings("deprecation")
        public void onReceivedError(WebView v, int code, String desc, String failingUrl) {          // API 21–22
            if (Build.VERSION.SDK_INT < 23 && failingUrl != null && failingUrl.startsWith(server)) showError(v, desc);
        }
    }

    // ───────────── разрешения, выбор файлов ─────────────
    private class Chrome extends WebChromeClient {
        @Override
        public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback cb) {
            if (Build.VERSION.SDK_INT < 23 || checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED) {
                cb.invoke(origin, true, false);
            } else {
                geoCallback = cb; geoOrigin = origin;
                requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION}, REQ_PERM_LOC);
            }
        }

        @Override
        public void onPermissionRequest(final PermissionRequest req) {      // камера для getUserMedia (съёмка документов)
            runOnUiThread(new Runnable() {
                @Override public void run() {
                    boolean wantsCam = false;
                    for (String r : req.getResources()) if (PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(r)) wantsCam = true;
                    if (!wantsCam) { req.deny(); return; }
                    if (Build.VERSION.SDK_INT < 23 || checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
                        req.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});
                    } else {
                        camRequest = req;
                        requestPermissions(new String[]{Manifest.permission.CAMERA}, REQ_PERM_CAM);
                    }
                }
            });
        }

        @Override
        public boolean onShowFileChooser(WebView v, ValueCallback<Uri[]> cb, FileChooserParams params) {
            if (fileCallback != null) fileCallback.onReceiveValue(null);
            fileCallback = cb;
            Intent i = new Intent(Intent.ACTION_GET_CONTENT);
            i.addCategory(Intent.CATEGORY_OPENABLE);
            List<String> mimes = new ArrayList<String>();
            String[] accept = params.getAcceptTypes();
            if (accept != null) for (String a : accept) {
                if (a == null) continue;
                for (String part : a.split(",")) {
                    part = part.trim();
                    if (part.length() == 0) continue;
                    if (part.startsWith(".")) {
                        String m = MimeTypeMap.getSingleton().getMimeTypeFromExtension(part.substring(1).toLowerCase());
                        if (m != null && !mimes.contains(m)) mimes.add(m);
                    } else if (part.contains("/") && !mimes.contains(part)) mimes.add(part);
                }
            }
            if (mimes.size() == 1) i.setType(mimes.get(0));
            else {
                i.setType("*/*");
                if (mimes.size() > 1) i.putExtra(Intent.EXTRA_MIME_TYPES, mimes.toArray(new String[0]));
            }
            i.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE);
            try {
                startActivityForResult(Intent.createChooser(i, null), REQ_FILE);
            } catch (ActivityNotFoundException e) {
                fileCallback = null;
                cb.onReceiveValue(null);
                return false;
            }
            return true;
        }
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] res) {
        boolean ok = res.length > 0 && res[0] == PackageManager.PERMISSION_GRANTED;
        if (code == REQ_PERM_LOC && geoCallback != null) {
            boolean any = false;
            for (int r : res) if (r == PackageManager.PERMISSION_GRANTED) any = true;
            geoCallback.invoke(geoOrigin, any, false);
            geoCallback = null;
        } else if (code == REQ_PERM_CAM && camRequest != null) {
            if (ok) camRequest.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE}); else camRequest.deny();
            camRequest = null;
        }
    }

    // ───────────── сохранение файлов с выбором места ─────────────
    private void askSaveLocation(String name, String mime) {
        Intent i = new Intent(Intent.ACTION_CREATE_DOCUMENT);
        i.addCategory(Intent.CATEGORY_OPENABLE);
        i.setType(mime == null || mime.length() == 0 ? "application/octet-stream" : mime);
        i.putExtra(Intent.EXTRA_TITLE, name);
        try {
            startActivityForResult(i, REQ_SAVE);
        } catch (ActivityNotFoundException e) {
            Toast.makeText(this, "Нет приложения для выбора папки", Toast.LENGTH_LONG).show();
            pendingBytes = null; pendingUrl = null;
        }
    }

    private void saveFromUrl(String url, String name, String mime) {
        pendingBytes = null; pendingUrl = url; pendingName = name; pendingMime = mime;
        askSaveLocation(name, mime);
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        if (req == REQ_FILE) {
            Uri[] results = res == RESULT_OK ? WebChromeClient.FileChooserParams.parseResult(res, data) : null;
            if (fileCallback != null) fileCallback.onReceiveValue(results);
            fileCallback = null;
        } else if (req == REQ_SAVE) {
            if (res != RESULT_OK || data == null || data.getData() == null) { pendingBytes = null; pendingUrl = null; return; }
            final Uri target = data.getData();
            final byte[] bytes = pendingBytes;
            final String url = pendingUrl;
            pendingBytes = null; pendingUrl = null;
            new Thread(new Runnable() {
                @Override public void run() { writeTarget(target, bytes, url); }
            }).start();
        }
    }

    private void toast(final String m) {
        runOnUiThread(new Runnable() { @Override public void run() { Toast.makeText(MainActivity.this, m, Toast.LENGTH_LONG).show(); } });
    }

    /** Запись выбранного пользователем файла: из байтов (отчёт) или потоковая загрузка с сервера (видео, архивы). */
    private void writeTarget(Uri target, byte[] bytes, String url) {
        OutputStream out = null;
        InputStream in = null;
        HttpURLConnection c = null;
        try {
            out = getContentResolver().openOutputStream(target);
            if (out == null) throw new Exception("cannot open target");
            if (bytes != null) {
                out.write(bytes);
            } else if (url != null) {
                c = (HttpURLConnection) new URL(url).openConnection();
                c.setConnectTimeout(30000);
                c.setReadTimeout(600000);
                c.setInstanceFollowRedirects(true);
                if (c.getResponseCode() >= 400) throw new Exception("HTTP " + c.getResponseCode());
                in = c.getInputStream();
                byte[] buf = new byte[65536];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            }
            out.flush();
            toast("✔ Сохранено / Saved");
        } catch (Exception e) {
            toast("Ошибка сохранения / Save error: " + e.getMessage());
        } finally {
            try { if (in != null) in.close(); } catch (Exception ignore) { }
            try { if (out != null) out.close(); } catch (Exception ignore) { }
            if (c != null) c.disconnect();
        }
    }

    /** One-time best-effort migration of legacy pending orders into Room. */
    private void migrateLegacyOutbox(SharedPreferences serverPrefs) {
        SharedPreferences old = getSharedPreferences("hm_native_outbox", MODE_PRIVATE);
        java.util.Map<String, ?> values = old.getAll();
        java.util.Set<String> ids = new java.util.HashSet<String>();
        for (String k : values.keySet()) if (k.startsWith("pending:") && Boolean.TRUE.equals(values.get(k))) ids.add(k.substring(8));
        for (String id : ids) {
            String base = old.getString("base:" + id, "");
            String token = old.getString("token:" + id, "");
            String body = old.getString("body:" + id, "");
            if (base.length() == 0 || body.length() == 0) continue;
            try {
                org.json.JSONObject envelope = new org.json.JSONObject();
                envelope.put("baseUrl", base);
                envelope.put("body", new org.json.JSONTokener(body).nextValue());
                org.prontofix.app.data.SyncRepository repo = new org.prontofix.app.data.SyncRepository(this);
                repo.enqueueOrder(envelope.toString(), token);
                old.edit().remove("pending:" + id).remove("base:" + id).remove("token:" + id).remove("body:" + id).apply();
                org.prontofix.app.data.QueueWork.request(this);
            } catch (Exception ignored) { /* Keep legacy entry for manual recovery. */ }
        }
    }

    // ───────────── мост для страницы (window.AndroidBridge) ─────────────
    private class Bridge {
        @JavascriptInterface
        public void queueOrderSync(String baseUrl, String token, String requestId, String jsonBody) {
            if (baseUrl == null || token == null || requestId == null || jsonBody == null) return;
            try {
                org.json.JSONObject envelope = new org.json.JSONObject();
                envelope.put("baseUrl", baseUrl);
                envelope.put("requestId", requestId);
                envelope.put("body", new org.json.JSONTokener(jsonBody).nextValue());
                new org.prontofix.app.data.SyncRepository(MainActivity.this).enqueueOrder(envelope.toString(), token);
                org.prontofix.app.data.QueueWork.request(MainActivity.this);
            } catch (Exception e) { toast("Ошибка постановки заказа в очередь: " + e.getMessage()); }
        }

        /** Отчёт (xlsx) из страницы: байты в base64 → окно «Сохранить как…» → запись в выбранное место. */
        @JavascriptInterface
        public void saveBase64(final String name, final String mime, final String b64) {
            final byte[] data = Base64.decode(b64, Base64.DEFAULT);
            runOnUiThread(new Runnable() {
                @Override public void run() {
                    pendingUrl = null; pendingBytes = data; pendingName = name; pendingMime = mime;
                    askSaveLocation(name, mime);
                }
            });
        }

        /** Файл с сервера: сначала выбор места, затем потоковая загрузка прямо в него. */
        @JavascriptInterface
        public void saveUrl(final String url, final String name, final String mime) {
            runOnUiThread(new Runnable() { @Override public void run() { saveFromUrl(url, name, mime); } });
        }

        /** Не гасить экран (пока включён трекинг). */
        @JavascriptInterface
        public void keepScreenOn(final boolean on) {
            runOnUiThread(new Runnable() {
                @Override public void run() {
                    if (on) getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                    else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                }
            });
        }

        @JavascriptInterface
        public void changeServer() {
            runOnUiThread(new Runnable() { @Override public void run() { showServerDialog(true); } });
        }

        @JavascriptInterface
        public String appVersion() { return "2.0"; }
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) web.goBack(); else super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        if (web != null) { root.removeView(web); web.destroy(); }
        super.onDestroy();
    }
}
