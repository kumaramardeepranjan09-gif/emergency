#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Wire.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Preferences.h>
#include <math.h>
#include "secrets.h"
#include "dashboard.h"

// ESP32-WROOM DevKit. DS18B20 buses each need a 4.7k pull-up to 3.3V.
constexpr int TEMP_PINS[2]={16,17}, RELAYS[2]={32,33};
constexpr int ENABLE[2]={25,14}, IN_A[2]={26,18}, IN_B[2]={27,19};
constexpr int BUZZER=23, SDA_PIN=21, SCL_PIN=22;
constexpr uint8_t MPU=0x68;
constexpr float TEMP_WARN=32, TEMP_TRIP=35, VIB_WARN=.25f, VIB_TRIP=.70f;
constexpr float ROT_WARN=30, ROT_TRIP=90;
constexpr uint64_t LIFE_MS=10ULL*60*60*1000;
constexpr uint32_t TEMP_STALE=6000, MOTION_STALE=500;
WebServer server(80);
Preferences prefs;
OneWire ow1(TEMP_PINS[0]), ow2(TEMP_PINS[1]);
DallasTemperature ds1(&ow1), ds2(&ow2);
struct Motor { int direction=0, speed=150; bool relay=false; uint64_t used=0; } motors[2];
float temp[2]={NAN,NAN}, accel[3]={0,0,1}, gyro[3]={0,0,0};
bool tempOK[2]={false,false}, mpuOK=false, motionSeeded=false;
float vibration=0, rotation=0, chipTemp=0;
uint32_t tempAt=0, motionAt=0, conversionAt=0, requestAt=0, sampleAt=0;
uint32_t lastTick=0, lastSave=0, bootAt=0, probeAt=0;
bool pending=false, locked=false, storageOK=false;
String reason="", status="STARTING", warning="Waiting for fresh sensors";
unsigned criticalSamples=0, warningSamples=0;
uint32_t motionWarningAt=0;
bool motionWarningSeen=false;
struct Event { uint32_t at=0; String text; } events[32];
unsigned eventCount=0;
String escaped(const String &s) {
  String out; out.reserve(s.length()+8);
  for (size_t i=0;i<s.length();i++) { char c=s[i];
    if(c=='"'||c=='\\') {out+='\\';out+=c;}
    else if(c=='\n') out+="\\n";
    else if((uint8_t)c>=32) out+=c;
  } return out;
}
void logEvent(const String &s) { events[eventCount%32].at=millis();events[eventCount%32].text=s; eventCount++; Serial.println(s); }
bool running(int i) {return motors[i].direction!=0 && motors[i].speed>0;}
void account() {
  uint32_t now=millis(), delta=now-lastTick; lastTick=now;
  for(int i=0;i<2;i++) if(running(i)) motors[i].used+=delta;
}
void output(int i) {
  analogWrite(ENABLE[i],0);
  digitalWrite(IN_A[i], motors[i].direction>0?HIGH:LOW);
  digitalWrite(IN_B[i], motors[i].direction<0?HIGH:LOW);
  if(motors[i].direction) analogWrite(ENABLE[i],motors[i].speed);
}
void stop(int i) {account();motors[i].direction=0;output(i);}
void setRelay(int i,bool on) {motors[i].relay=on;digitalWrite(RELAYS[i],on?LOW:HIGH);}
void allOff() {stop(0);stop(1);setRelay(0,false);setRelay(1,false);}
void saveUsage() {
  if(!storageOK)return;
  account();
  bool ok=true;
  for(int i=0;i<2;i++) {
    String key="used"+String(i);
    if(prefs.putULong64(key.c_str(),motors[i].used)!=sizeof(uint64_t))ok=false;
  }
  if(!ok)storageOK=false;
  lastSave=millis();
}
void trip(const String &s) {
  bool first=!locked; locked=true;
  if(first){ reason=s;logEvent("CRITICAL: "+s); }
  allOff();digitalWrite(BUZZER,HIGH);
  if(first)saveUsage();
}
bool writeReg(uint8_t reg,uint8_t value) {
  Wire.beginTransmission(MPU);Wire.write(reg);Wire.write(value);return Wire.endTransmission()==0;
}
bool readBytes(uint8_t reg,uint8_t *out,uint8_t n) {
  Wire.beginTransmission(MPU);Wire.write(reg);
  if(Wire.endTransmission(false)!=0)return false;
  if(Wire.requestFrom(MPU,n,(uint8_t)true)!=n)return false;
  for(int i=0;i<n;i++)out[i]=Wire.read();return true;
}
void initMPU() {
  uint8_t who=0;
  mpuOK=readBytes(0x75,&who,1)&&who==0x68&&writeReg(0x6B,0)&&
    writeReg(0x1A,3)&&writeReg(0x19,9)&&writeReg(0x1C,0)&&writeReg(0x1B,0);
  motionSeeded=false;
}
int16_t word(const uint8_t *p) {return (int16_t)(((uint16_t)p[0]<<8)|p[1]);}
void readMotion() {
  uint8_t b[14];
  if(!readBytes(0x3B,b,14)){mpuOK=false;motionSeeded=false;criticalSamples=warningSamples=0;return;}
  float a[3], magnitude=0, delta=0;
  for(int i=0;i<3;i++) {
    a[i]=word(b+2*i)/16384.f;
    gyro[i]=word(b+8+2*i)/131.f;
    magnitude+=a[i]*a[i]; delta+=(a[i]-accel[i])*(a[i]-accel[i]);
  }
  // Detect both departure from gravity and abrupt vector changes (including tilt).
  vibration=max(fabsf(sqrtf(magnitude)-1.f),motionSeeded?sqrtf(delta):0.f);
  for(int i=0;i<3;i++)accel[i]=a[i];
  rotation=sqrtf(gyro[0]*gyro[0]+gyro[1]*gyro[1]+gyro[2]*gyro[2]);
  chipTemp=word(b+6)/340.f+36.53f;
  mpuOK=true; motionSeeded=true; motionAt=millis();
  warningSamples=(vibration>VIB_WARN||rotation>ROT_WARN)?min(warningSamples+1,3U):0;
  if(warningSamples){motionWarningAt=millis();motionWarningSeen=true;}
  criticalSamples=(vibration>VIB_TRIP||rotation>ROT_TRIP)?min(criticalSamples+1,2U):0;
}
bool sensorsReady() {
  uint32_t now=millis();
  return tempOK[0]&&tempOK[1]&&mpuOK&&motionSeeded&&
    now-tempAt<TEMP_STALE&&now-motionAt<MOTION_STALE;
}
bool resetSafe() {
  return sensorsReady()&&storageOK&&temp[0]<=TEMP_WARN&&temp[1]<=TEMP_WARN&&
    vibration<=VIB_WARN&&rotation<=ROT_WARN;
}
void safety() {
  if((tempOK[0]&&temp[0]>TEMP_TRIP)||(tempOK[1]&&temp[1]>TEMP_TRIP))trip("Temperature above 35 C");
  else if(criticalSamples>=2)trip("Excessive movement / vibration");
  else if(motionSeeded&&(vibration>1.5f||rotation>180))trip("Severe sudden movement");
  else if(!storageOK)trip("Usage storage unavailable");
  else if(!sensorsReady() && (running(0)||running(1)||motors[0].relay||motors[1].relay))trip("Sensor missing or stale");
  else if((motors[0].used>=LIFE_MS&&running(0))||(motors[1].used>=LIFE_MS&&running(1)))trip("Motor service budget exhausted");
  bool motionWarning=motionWarningSeen&&millis()-motionWarningAt<3000;
  String next=locked?"CRITICAL":!sensorsReady()?"WARNING":
    (temp[0]>TEMP_WARN||temp[1]>TEMP_WARN||motionWarning)?"WARNING":"NORMAL";
  warning=locked?reason:!sensorsReady()?"Sensor missing / waiting for fresh readings":
    temp[0]>TEMP_WARN||temp[1]>TEMP_WARN?"Temperature above 32 C":
    motionWarning?"Sudden movement / vibration detected":"System operating normally";
  if(next!=status){logEvent(next+": "+warning);status=next;}
  digitalWrite(BUZZER,locked?HIGH:LOW);
}
void updateTemps() {
  uint32_t now=millis();
  if(pending&&now-conversionAt>=800) {
    temp[0]=ds1.getTempCByIndex(0);temp[1]=ds2.getTempCByIndex(0);
    for(int i=0;i<2;i++)tempOK[i]=isfinite(temp[i])&&temp[i]!=DEVICE_DISCONNECTED_C&&temp[i]>=-55&&temp[i]<=125;
    tempAt=now;pending=false;
  }
  if(!pending&&now-requestAt>=1500) {
    ds1.requestTemperatures();ds2.requestTemperatures();conversionAt=millis();requestAt=conversionAt;pending=true;
  }
}
String num(float v,int digits=2){return isfinite(v)?String(v,digits):"null";}
float risk(int i) {
  if(!sensorsReady())return -1;
  float thermal=constrain((temp[i]-25.f)/10.f,0.f,1.f)*100;
  float motion=max(constrain(vibration/VIB_TRIP,0.f,1.f),constrain(rotation/ROT_TRIP,0.f,1.f))*100;
  float age=min(100.f,(float)motors[i].used/LIFE_MS*100);
  return max(thermal,max(motion,age));
}
void api() {
  account();safety();
  String j="{\"mode\":\"hardware\",\"uptime\":"+String(millis()/1000)+",\"status\":\""+status+"\",\"warning\":\""+escaped(warning)+"\",\"critical\":"+(locked?"true":"false")+",\"ready\":"+(sensorsReady()?"true":"false")+",\"storageOK\":"+(storageOK?"true":"false")+",\"t1\":"+num(temp[0])+",\"t2\":"+num(temp[1])+",\"t1OK\":"+(tempOK[0]?"true":"false")+",\"t2OK\":"+(tempOK[1]?"true":"false")+",\"mpuOK\":"+(mpuOK?"true":"false")+",\"vib\":"+num(vibration,3)+",\"rot\":"+num(rotation)+",\"mt\":"+num(chipTemp)+",\"motors\":[";
  for(int i=0;i<2;i++) {
    if(i)j+=",";
    j+="{\"id\":"+String(i+1)+",\"state\":\""+(motors[i].direction>0?"FORWARD":motors[i].direction<0?"REVERSE":"STOP")+"\",\"speed\":"+String(motors[i].speed)+",\"relay\":"+(motors[i].relay?"true":"false")+",\"usedSeconds\":"+String((double)motors[i].used/1000,3)+",\"remainingSeconds\":"+String((double)(motors[i].used<LIFE_MS?LIFE_MS-motors[i].used:0)/1000,3)+",\"risk\":"+num(risk(i))+"}";
  }
  j+="],\"events\":[";
  unsigned count=min(eventCount,32U);
  for(unsigned n=0;n<count;n++){if(n)j+=",";Event &e=events[(eventCount-1-n)%32];j+="{\"at\":"+String(e.at/1000)+",\"text\":\""+escaped(e.text)+"\"}";}
  j+="],\"eventCount\":"+String(eventCount)+"}";
  server.sendHeader("Cache-Control","no-store");server.send(200,"application/json",j);
}
bool isOffCommand(const String &c) {return c=="M1S"||c=="M2S"||c=="R1OFF"||c=="R2OFF";}
void command() {
  if(server.header("X-MotorGuard")!="1"){server.send(403,"text/plain","Missing command header");return;}
  account();safety();
  if(!server.hasArg("c")){server.send(400,"text/plain","Missing command");return;}
  String c=server.arg("c");c.toUpperCase();
  if(c=="ALLSTOP"){trip("Operator emergency stop");safety();server.send(200,"text/plain","All outputs off; safety lock active");return;}
  if(c=="RESET") {
    if(!resetSafe()){server.send(409,"text/plain","Reset blocked: all sensors must be fresh, connected and below warning thresholds");return;}
    locked=false;reason="";criticalSamples=warningSamples=0;motionWarningSeen=false;allOff();logEvent("Safety reset; outputs remain OFF");safety();server.send(200,"text/plain","OK");return;
  }
  bool valid=isOffCommand(c)||c=="M1F"||c=="M1R"||c=="M2F"||c=="M2R"||c=="R1ON"||c=="R2ON"||c=="SPEED1"||c=="SPEED2";
  if(!valid){server.send(400,"text/plain","Unknown command");return;}
  if(!isOffCommand(c)&&(locked||!sensorsReady()||!storageOK)){server.send(423,"text/plain","Outputs inhibited: resolve fault and reset");return;}
  int i=(c.indexOf('2')>=0)?1:0;
  if(c.startsWith("SPEED")) {
    String v=server.arg("v"); bool digits=v.length()>0&&v.length()<=3;
    for(size_t n=0;n<v.length();n++)if(v[n]<'0'||v[n]>'9')digits=false;
    if(!digits||v.toInt()>255){server.send(400,"text/plain","Speed must be an integer from 0 to 255");return;}
    if(motors[i].used>=LIFE_MS){server.send(409,"text/plain","Service budget exhausted");return;}
    motors[i].speed=v.toInt();output(i);
  } else if(c.startsWith("R"))setRelay(i,c.endsWith("ON"));
  else if(c.endsWith("S")){stop(i);saveUsage();}
  else {
    if(motors[i].used>=LIFE_MS){server.send(409,"text/plain","Service budget exhausted");return;}
    int direction=c.endsWith("F")?1:-1;
    // No automatic reversal while energized: stop and request again explicitly.
    if(motors[i].direction!=0&&motors[i].direction!=direction){server.send(409,"text/plain","Stop the motor before reversing");return;}
    motors[i].direction=direction;output(i);
  }
  logEvent("Command: "+c);safety();server.send(200,"text/plain","OK");
}
void setup() {
  Serial.begin(115200);
  for(int i=0;i<2;i++) {
    digitalWrite(RELAYS[i],HIGH);pinMode(RELAYS[i],OUTPUT);
    pinMode(ENABLE[i],OUTPUT);pinMode(IN_A[i],OUTPUT);pinMode(IN_B[i],OUTPUT);output(i);setRelay(i,false);
  }
  pinMode(BUZZER,OUTPUT);digitalWrite(BUZZER,LOW);
  storageOK=prefs.begin("motorguard",false);
  if(storageOK)for(int i=0;i<2;i++){String k="used"+String(i);motors[i].used=prefs.getULong64(k.c_str(),0);}
  lastTick=lastSave=bootAt=millis();
  ds1.begin();ds2.begin();ds1.setResolution(12);ds2.setResolution(12);
  ds1.setWaitForConversion(false);ds2.setWaitForConversion(false);
  Wire.begin(SDA_PIN,SCL_PIN);Wire.setClock(100000);Wire.setTimeOut(25);initMPU();
  WiFi.mode(WIFI_AP);WiFi.setSleep(false);
  if(strlen(AP_PASSWORD)<8||strlen(AP_PASSWORD)>63||!WiFi.softAP(AP_SSID,AP_PASSWORD,1,false,4)){
    trip("Wi-Fi AP configuration failed");while(true){delay(100);}
  }
  server.on("/",HTTP_GET,[]{server.sendHeader("Cache-Control","no-store");server.send_P(200,"text/html; charset=utf-8",PAGE);});
  const char *headers[]={"X-MotorGuard"};server.collectHeaders(headers,1);
  server.on("/api",HTTP_GET,api);server.on("/cmd",HTTP_POST,command);
  server.onNotFound([]{server.send(404,"text/plain","Not found");});server.begin();
  Serial.print("Dashboard AP ready at ");Serial.println(WiFi.softAPIP());
  logEvent("Boot complete; outputs OFF, waiting for sensors");
  requestAt=millis()-1500;updateTemps();
}
void loop() {
  account();updateTemps();uint32_t now=millis();
  if(!mpuOK&&now-probeAt>=2000){probeAt=now;initMPU();}
  if(now-sampleAt>=100){sampleAt=now;if(mpuOK)readMotion();}
  safety(); // Enforce safety before accepting a new actuator command.
  server.handleClient();
  if(now-lastSave>=30000)saveUsage();
  delay(1);
}
