#pragma once
#include "OneWire.h"
#define DEVICE_DISCONNECTED_C -127
struct DallasTemperature {
 float value=28;
 DallasTemperature(OneWire*){}void begin(){}void setResolution(int){}void setWaitForConversion(bool){}void requestTemperatures(){}float getTempCByIndex(int){return value;}
};
