package local.nyako.cwbpattern;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;

/** Static geometry stimulus, NOT a CWB reader or a calibration tool. */
public final class MainActivity extends Activity {
    private Pattern pattern;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().setDecorFitsSystemWindows(false);
        WindowManager.LayoutParams attrs=getWindow().getAttributes();
        attrs.layoutInDisplayCutoutMode=WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_ALWAYS;
        getWindow().setAttributes(attrs);
        pattern=new Pattern(); setContentView(pattern); applyIntent(getIntent());
        pattern.post(() -> {
            WindowInsetsController controller=pattern.getWindowInsetsController();
            if(controller!=null) {
                controller.hide(WindowInsets.Type.systemBars());
                controller.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            }
        });
    }
    @Override protected void onNewIntent(Intent intent) { super.onNewIntent(intent); setIntent(intent); applyIntent(intent); }
    private void applyIntent(Intent intent) {
        pattern.stopStimulus();
        pattern.patch=intent.getIntExtra("patch",Color.WHITE);
        pattern.control=intent.getBooleanExtra("control",false);
        // Optional finite lab stimulus; never writes system brightness/settings.
        // Missing extra restores the Activity to the system's normal brightness.
        int testPercent=intent.getIntExtra("testBrightnessPercent",-1);
        WindowManager.LayoutParams attrs=getWindow().getAttributes();
        attrs.screenBrightness=testPercent>=1 && testPercent<=100
                ? testPercent/100f : WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE;
        getWindow().setAttributes(attrs);
        pattern.startStimulus(intent.getIntExtra("animateMs",0));
        pattern.invalidate();
    }
    @Override protected void onPause() { pattern.stopStimulus(); super.onPause(); }
    private final class Pattern extends View {
        final Paint paint=new Paint();
        final int[] colors={Color.WHITE,Color.RED,Color.GREEN,Color.BLUE,Color.BLACK};
        final String[] labels={"白","红","绿","蓝","黑"};
        int patch=Color.WHITE; boolean control=false;
        long stimulusDeadline=0; boolean stimulusVisible=false, stimulusPhase=false;
        final Runnable stimulus=new Runnable() {
            @Override public void run() {
                if(SystemClock.uptimeMillis()>=stimulusDeadline) { stopStimulus(); return; }
                stimulusPhase=!stimulusPhase; invalidate();
                postDelayed(this,16);
            }
        };
        Pattern() { super(MainActivity.this); }
        void startStimulus(int duration) {
            if(duration<=0) return;
            // Explicit finite display stimulus ONLY, not a CWB capture loop.
            stimulusDeadline=SystemClock.uptimeMillis()+Math.min(duration,15000);
            stimulusVisible=true; post(stimulus);
        }
        void stopStimulus() {
            removeCallbacks(stimulus); stimulusDeadline=0;
            if(stimulusVisible) { stimulusVisible=false; invalidate(); }
        }
        @Override protected void onDraw(Canvas canvas) {
            canvas.drawColor(Color.WHITE);
            canvas.save(); canvas.scale(getWidth()/1440f,getHeight()/3168f);
            int x=control ? 250 : 1010, y=control ? 700 : 148;
            paint.setColor(patch); canvas.drawRect(x,y,x+38,y+42,paint);
            if(stimulusVisible) {
                paint.setColor(stimulusPhase ? Color.BLACK : Color.WHITE);
                // Far from ALS ROI: tests global cache invalidation on redraw.
                canvas.drawRect(70,2520,170,2580,paint);
            }
            paint.setTextSize(38); paint.setColor(Color.BLACK);
            canvas.drawText("一加13：原生ROI 1010,148 — 1048,190",80,2700,paint);
            canvas.drawText("静态画面：无传感器订阅、计时刷新、网络和后台服务",80,2770,paint);
            canvas.drawText(control ? "当前：异位对照色块" : "当前：官方ROI色块",80,2840,paint);
            for(int i=0;i<5;++i) {
                paint.setColor(0xffdddddd); canvas.drawRect(70+i*260,2910,300+i*260,3030,paint);
                paint.setColor(Color.BLACK); canvas.drawText(labels[i],155+i*260,2988,paint);
            }
            canvas.drawText("点上方按钮换色；点此行切换官方ROI / 异位对照",80,3110,paint);
            canvas.restore();
        }
        @Override public boolean onTouchEvent(MotionEvent event) {
            if(event.getAction()!=MotionEvent.ACTION_UP) return true;
            float x=event.getX()*1440/getWidth(), y=event.getY()*3168/getHeight();
            if(y>=2910 && y<=3030) {
                int index=(int)((x-70)/260);
                if(x>=70 && index>=0 && index<5) patch=colors[index];
            } else if(y>3030) control=!control;
            invalidate(); performClick(); return true;
        }
        @Override public boolean performClick() { super.performClick(); return true; }
    }
}
