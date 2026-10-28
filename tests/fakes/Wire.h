#pragma once
#include "Arduino.h"
struct WireFake {
 std::deque<uint8_t> bytes;bool fail=false;
 void begin(int,int){}void setClock(int){}void setTimeOut(int){}void beginTransmission(uint8_t){}void write(uint8_t){}
 int endTransmission(bool=true){return fail?1:0;}uint8_t requestFrom(uint8_t,uint8_t n,uint8_t){return fail?0:(bytes.size()>=n?n:0);}
 int read(){auto b=bytes.front();bytes.pop_front();return b;}
};inline WireFake Wire;
