/* Runs the bomb time / overtime code that dllpatch.patch_bomb_rules writes into a DO mode DLL, natively as a 32-bit
   Linux program: the DLL's image laid out in memory, GetTime faked, a scene with its list of bombs and its round clock.
   Built by tests/test_batch14.py (gcc -m32 -nostdlib), skipped without it.  otcode.h: IMG[], R_RVA (scene Run hook),
   H_RVA ("__timeout__" hook), SLOT_RVA (GetTime's import slot), CLOCK (the clock's offset in the scene), OVER (the scene's "round over, restart pending" byte). */
#include "otcode.h"
typedef unsigned int u32;
static unsigned char img[IMG_SIZE] __attribute__((aligned(4096)));
static int fails;
static void sys_write(const char*s,int n){ int r; __asm__ volatile("int $0x80":"=a"(r):"a"(4),"b"(1),"c"(s),"d"(n):"memory"); }
static int slen(const char*s){int n=0;while(s[n])n++;return n;}
static void puts_(const char*s){sys_write(s,slen(s));sys_write("\n",1);}
static void putn(u32 v){char b[12];int i=11;b[i]=0;do{b[--i]='0'+v%10;v/=10;}while(v);sys_write(b+i,11-i);}
#define CHECK(c,msg) do{ if(!(c)){ puts_(msg); fails++; } }while(0)
float now_ms;
float __attribute__((cdecl)) f_time(void){ return now_ms; }
static unsigned char scene[0x800], clk[0x60], bomb[0x200];
static u32 list[4];
u32 saved_esp, result, entry_addr, entry_scene;
void run_hook(void); void to_hook(void); void back_stub(void); void orig_stub(void);
__asm__(".globl run_hook\nrun_hook: pusha\n movl %esp,saved_esp\n movl entry_scene,%ecx\n movl $0x1111,%ebx\n movl $0x2222,%ebp\n"
        " movl $0x3333,%esi\n movl $0x4444,%edi\n jmp *entry_addr\n"
        ".globl to_hook\nto_hook: pusha\n movl %esp,saved_esp\n pushl entry_scene\n pushl $to_ret\n jmp *entry_addr\n"
        "to_ret: movl $6,result\n movl saved_esp,%esp\n popa\n ret\n"
        ".globl back_stub\nback_stub: movl $8,result\n movl saved_esp,%esp\n popa\n ret\n"
        ".globl orig_stub\norig_stub: movl $7,result\n movl saved_esp,%esp\n popa\n ret\n");
static void jmp_to(u32 at, void(*f)(void)){ img[at]=0xe9; *(u32*)(img+at+1)=(u32)f-((u32)img+at+5); }
static int Run(void){ result=0; entry_addr=(u32)img+R_RVA; entry_scene=(u32)scene; run_hook(); return result; }
static int Timeout(void){ result=0; entry_addr=(u32)img+H_RVA; entry_scene=(u32)scene; to_hook(); return result; }
#define F(p,o) (*(float*)((p)+(o)))
#define U(p,o) (*(u32*)((p)+(o)))
void _start(void){
  __asm__ volatile("int $0x80"::"a"(125),"b"((u32)img),"c"(IMG_SIZE),"d"(7));   /* mprotect RWX */
  for(u32 i=0;i<sizeof(IMG);i++) img[i]=IMG[i];
  U(img,SLOT_RVA)=(u32)f_time;
  jmp_to(R_RVA+6, back_stub); jmp_to(H_RVA+6, orig_stub);       /* where the hooks go back to the DLL's own code */
  U(scene,CLOCK)=(u32)clk; U(scene,0xfc)=(u32)list; U(scene,0x104)=1; list[0]=(u32)bomb;
  U(bomb,0x1b0)=1; F(bomb,0x194)=100000.0f; F(bomb,0x1d8)=100000.0f;
  /* the scene's Run: the planting time moved once by fuse - 20 s (fuse 40 s) */
  now_ms=100500.0f; CHECK(Run()==8,"run: back to the DLL");
  CHECK(F(bomb,0x194)==120000.0f&&F(bomb,0x1d8)==120000.0f,"run: planting time moved by 20 s");
  now_ms=101000.0f; Run(); CHECK(F(bomb,0x194)==120000.0f,"run: moved once only");
  /* 0:00 with the bomb ticking (8 s after planting): the clock shows its own seconds, the round goes on */
  now_ms=108000.0f; F(clk,0x30)=-0.01f; U(clk,0x2c)=0; clk[0x34]=1;
  CHECK(Timeout()==6,"timeout, ticking: the round goes on (the DLL's handler not run)");
  CHECK(F(clk,0x30)>32.04f&&F(clk,0x30)<32.06f&&U(clk,0x2c)==0&&clk[0x34]==0,"timeout, ticking: its 32 s on the clock (0:00 as it blows up)");
  clk[0x34]=1; now_ms=108100.0f; Run(); CHECK(clk[0x34]==0&&F(clk,0x38)==108100.0f,"run after timeout: the clock runs again");
  clk[0x34]=1; Run(); CHECK(clk[0x34]==1,"run: the clock restarted once only");
  /* late: still ticking at the next 0:00 -> a quarter of a second more (still 0:00) */
  now_ms=145000.0f; F(clk,0x30)=-0.01f; CHECK(Timeout()==6&&F(clk,0x30)==0.25f,"timeout, ticking late: 0.25 s more");
  /* it blew up and left the scene's list at once: the next 0:00 waits for its win (3 s), not the defenders' */
  now_ms=146000.0f; U(bomb,0x1b0)=2; Run();
  U(scene,0x104)=0; now_ms=147000.0f; Run();
  now_ms=148500.0f; F(clk,0x30)=-0.01f; CHECK(Timeout()==6&&F(clk,0x30)==0.9f,"timeout after the boom (bomb gone from the list): wait, 0:00");
  now_ms=158000.0f; F(clk,0x30)=-0.01f; CHECK(Timeout()==7,"timeout long after the boom: the DLL's own handler (defenders win)");
  /* the round already won (restart pending): a 0:00 now is let go, the clock as it is */
  now_ms=158500.0f; scene[OVER]=1; F(clk,0x30)=-0.01f; U(clk,0x2c)=0;
  CHECK(Timeout()==6&&F(clk,0x30)==-0.01f,"timeout, round over: let go");
  scene[OVER]=0;
  /* the 0:00 of the round before, handled after the restart (clock 7:00 again): let go - not the defenders' win */
  U(clk,0x2c)=7; F(clk,0x30)=0.0f; CHECK(Timeout()==6&&U(clk,0x2c)==7&&F(clk,0x30)==0.0f,"stale timeout, new round: let go");
  U(clk,0x2c)=0; F(clk,0x30)=12.0f; CHECK(Timeout()==6&&F(clk,0x30)==12.0f,"stale timeout, seconds left: let go");
  U(clk,0x2c)=0; F(clk,0x30)=-0.01f;
  /* no bomb at all in this round */
  U(scene,0x104)=1; U(bomb,0x1b0)=0; now_ms=200000.0f; Run();
  now_ms=300000.0f; CHECK(Timeout()==7,"timeout, no bomb: the DLL's own handler");
  U(scene,CLOCK)=0; CHECK(Run()==8&&Timeout()==7,"no clock: nothing");
  puts_(fails?"FAILED":"all ok"); putn(fails); sys_write("\n",1);
  __asm__ volatile("int $0x80"::"a"(1),"b"(fails));
}
