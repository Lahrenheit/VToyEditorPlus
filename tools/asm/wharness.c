/* Runs weather.s (the ".vtoyw" stub put in place of a mode DLL's "call [AddShower]") natively as a 32-bit Linux
   program: AddShower, LoadSound and ReleaseSound faked.  Built by tests/test_batch14.py (gcc -m32 -nostdlib). */
#include "wcode.h"
typedef unsigned int u32;
unsigned char sec[0x2000] __attribute__((aligned(4096)));
static int fails;
static void sys_write(const char*s,int n){ int r; __asm__ volatile("int $0x80":"=a"(r):"a"(4),"b"(1),"c"(s),"d"(n):"memory"); }
static int slen(const char*s){int n=0;while(s[n])n++;return n;}
static void puts_(const char*s){sys_write(s,slen(s));sys_write("\n",1);}
static void putn(u32 v){char b[12];int i=11;b[i]=0;do{b[--i]='0'+v%10;v/=10;}while(v);sys_write(b+i,11-i);}
static int seq(const char*a,const char*b){while(*a&&*a==*b){a++;b++;}return *a==*b;}
#define CHECK(c,msg) do{ if(!(c)){ puts_(msg); fails++; } }while(0)
static unsigned char shw[0x100]; static int showers, bad, nrel, nload; static char lastname[64];
static u32 ret_shower=1;
u32 __attribute__((cdecl)) f_show(u32 obj,float*pos,float w,float d,float*sp){ showers++;
  if(obj!=0x1234||pos[1]!=5000.0f||w!=30000.0f||d!=30000.0f||sp[1]!=-1500.0f) bad++;
  for(int i=0;i<0x100;i++) shw[i]=0x5a; return ret_shower?(u32)shw:0; }
void __attribute__((cdecl)) f_rel(int h){ nrel++; }
int __attribute__((cdecl)) f_load(u32*cs,int b,float f,float g){ const char*n=(const char*)cs[0]; int i=0; while(n[i]&&i<63){lastname[i]=n[i];i++;} lastname[i]=0;
  if((u32)(i+1)!=cs[1]||(b&0xff)!=0||f!=0.0f||g!=1000000.0f) bad++; return 0x7000+nload++; }
static u32 slot_show=(u32)f_show, slot_rel=(u32)f_rel, slot_load=(u32)f_load;
float pos[3]={0,5000.0f,0}, spd[3]={0,-1500.0f,0};
u32 got_eax, esp_before, esp_after, regs_ok;
void caller(void);
/* as the mode DLL calls it: 5 arguments, call, the caller takes them off; ebx, esi, edi, ebp must come back */
__asm__(".globl caller\ncaller: pusha\n movl $0x1111,%ebx\n movl $0x2222,%esi\n movl $0x3333,%edi\n movl $0x4444,%ebp\n"
        " movl %esp,esp_before\n pushl $spd\n pushl $0x46ea6000\n pushl $0x46ea6000\n pushl $pos\n pushl $0x1234\n"
        " movl $sec,%eax\n call *%eax\n addl $20,%esp\n movl %esp,esp_after\n movl %eax,got_eax\n"
        " xorl %eax,%eax\n cmpl $0x1111,%ebx\n jne 1f\n cmpl $0x2222,%esi\n jne 1f\n cmpl $0x3333,%edi\n jne 1f\n cmpl $0x4444,%ebp\n jne 1f\n"
        " movl $1,%eax\n1: movl %eax,regs_ok\n popa\n ret\n");
static void P(u32 off,u32 v){*(u32*)(sec+off)=v;}
void _start(void){
  __asm__ volatile("int $0x80"::"a"(125),"b"((u32)sec),"c"(0x2000),"d"(7));
  for(u32 i=0;i<sizeof(CODE);i++) sec[i]=CODE[i];
  P(0x800,(u32)&slot_show-(u32)sec); P(0x808,(u32)&slot_load-(u32)sec); P(0x80c,(u32)&slot_rel-(u32)sec);
  P(0x804,0); caller();
  CHECK(showers==1&&got_eax==(u32)shw&&esp_after==esp_before&&regs_ok,"storm: AddShower as before, its shower back, stack and registers");
  CHECK(shw[0xe8]==0x5a&&nrel==0&&nload==0,"storm: the shower untouched");
  P(0x804,1); caller();
  { int ok=shw[0xe8]==0&&shw[0xb0]==0x5a; for(int o=0xb4;o<0xcc;o++) ok&=shw[o]==0; CHECK(ok&&nrel==6,"calm: no flashes, thunders released"); }
  { const char*b="wavs/mp_x_trueno bajo_2.wav"; int lb=slen(b); *(u32*)(sec+0xc00+64*5)=lb+1; for(int j=0;j<lb;j++) sec[0xc04+64*5+j]=b[j]; }
  P(0x804,0); nrel=nload=0; caller();
  CHECK(nrel==1&&nload==1&&*(u32*)(shw+0xc4)==0x7000&&*(u32*)(shw+0xc0)==0x5a5a5a5au&&seq(lastname,"wavs/mp_x_trueno bajo_2.wav"),"sounds: the second low thunder replaced");
  ret_shower=0; nrel=nload=0; caller(); CHECK(got_eax==0&&nrel==0&&nload==0&&esp_after==esp_before&&regs_ok,"no shower: nothing done");
  CHECK(bad==0,"arguments");
  puts_(fails?"FAILED":"all ok"); putn(fails); sys_write("\n",1);
  __asm__ volatile("int $0x80"::"a"(1),"b"(fails));
}
