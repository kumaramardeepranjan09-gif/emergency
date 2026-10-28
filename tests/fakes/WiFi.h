#pragma once
#include "Arduino.h"
struct WiFiFake {void mode(int){}void setSleep(bool){}bool softAP(const char*,const char*,int,bool,int){return true;}String softAPIP(){return "192.168.4.1";}};
inline WiFiFake WiFi;
