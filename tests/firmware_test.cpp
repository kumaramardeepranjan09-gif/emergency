// Runs the actual firmware functions with deterministic hardware substitutes.
#include "../firmware/src/main.cpp"
#include <cassert>
#include <iostream>
void fresh(){tempAt=motionAt=millis();}
void resetFixture(){
 fakeMillis=10000;lastTick=lastSave=millis();tempAt=motionAt=millis();
 temp[0]=temp[1]=28;tempOK[0]=tempOK[1]=true;mpuOK=motionSeeded=storageOK=true;
 vibration=rotation=0;criticalSamples=warningSamples=0;motionWarningSeen=false;locked=false;reason="";status="NORMAL";
 for(auto &m:motors)m=Motor();eventCount=0;prefs.fail=false;Wire.fail=false;Wire.bytes.clear();
 server.clientHeader="1";server.args.clear();server.response=0;allOff();
}
int cmd(const char *c,const char *v=nullptr){server.args.clear();server.args["c"]=c;if(v)server.args["v"]=v;command();return server.response;}
void motion(float g,float rate){
 Wire.bytes.clear();int16_t vals[7]={0,0,(int16_t)(g*16384),0,(int16_t)(rate*131),0,0};
 for(auto v:vals){Wire.bytes.push_back((uint16_t)v>>8);Wire.bytes.push_back(v&255);}
 readMotion();safety();
}
int main(){
 resetFixture();assert(cmd("M1F")==200);temp[0]=32;safety();assert(status=="NORMAL");
 temp[0]=32.01f;safety();assert(status=="WARNING"&&!locked&&running(0));
 temp[0]=35;safety();assert(!locked);temp[0]=35.01f;safety();assert(locked&&!running(0)&&pwmPins[25]==0);
 assert(cmd("M2F")==423);assert(cmd("RESET")==409);assert(cmd("R1OFF")==200);
 temp[0]=28;tempOK[1]=false;assert(cmd("RESET")==409);tempOK[1]=true;fresh();assert(cmd("RESET")==200);assert(!running(0));
 resetFixture();cmd("M1F");cmd("M2R");cmd("R1ON");cmd("R2ON");motion(1,100);assert(!locked&&criticalSamples==1);motion(1,100);assert(locked&&!running(0)&&!running(1)&&!motors[0].relay&&!motors[1].relay);
 resetFixture();motion(1,45);assert(status=="WARNING");motion(1,0);assert(status=="WARNING");fakeMillis+=3001;fresh();safety();assert(status=="NORMAL");
 resetFixture();cmd("M1F");motion(1,200);assert(locked); // Severe shock: no debounce delay.
 resetFixture();cmd("M1F");fakeMillis+=501;safety();assert(locked); // Stale MPU.
 resetFixture();cmd("R1ON");tempOK[0]=false;safety();assert(locked&&!motors[0].relay);
 resetFixture();cmd("M1F");Wire.fail=true;readMotion();safety();assert(!mpuOK&&locked);assert(risk(0)<0);
 resetFixture();cmd("M1F");assert(cmd("M1R")==409);cmd("M1S");assert(cmd("M1R")==200);
 resetFixture();for(auto v:{"","abc","-1","256","12x","2.5"})assert(cmd("SPEED1",v)==400);assert(motors[0].speed==150);
 resetFixture();cmd("M1F");fakeMillis+=1000;account();assert(motors[0].used==1000&&motors[1].used==0);fresh();cmd("SPEED1","0");fakeMillis+=1000;account();assert(motors[0].used==1000);
 resetFixture();fakeMillis=UINT32_MAX-50;lastTick=fakeMillis;fresh();cmd("M1F");fakeMillis=49;account();assert(motors[0].used==100); // millis rollover.
 resetFixture();motors[0].used=LIFE_MS-1;cmd("M1F");fakeMillis+=2;account();fresh();safety();assert(locked);assert(cmd("RESET")==200);assert(cmd("M1F")==409);
 resetFixture();cmd("M1F");prefs.fail=true;saveUsage();safety();assert(!storageOK&&locked&&!running(0));
 resetFixture();server.clientHeader="";assert(cmd("M1F")==403&&!running(0));
 resetFixture();cmd("M1F");cmd("R1ON");assert(cmd("ALLSTOP")==200&&locked&&!running(0)&&!motors[0].relay);
 resetFixture();tempAt=millis()-TEMP_STALE;assert(cmd("M1F")==423);
 resetFixture();pending=true;conversionAt=millis()-800;ds1.value=-127;ds2.value=28;requestAt=millis();updateTemps();assert(!tempOK[0]&&tempOK[1]);
 std::cout<<"PASS: actual firmware thermal boundaries, motion debounce/severe trip, stale/missing sensors, reset, reversal, PWM parsing, independent usage, millis rollover, life exhaustion, storage failure, POST header and emergency shutdown\n";
}
