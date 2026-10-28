#pragma once
#include "Arduino.h"
struct Preferences {
 bool fail=false;std::map<std::string,uint64_t> saved;
 bool begin(const char*,bool){return !fail;}
 uint64_t getULong64(const char *k,uint64_t d){return saved.count(k)?saved[k]:d;}
 size_t putULong64(const char*k,uint64_t v){if(fail)return 0;saved[k]=v;return sizeof(uint64_t);}
};
