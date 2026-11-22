/* Runs the bomb zones code (bombzones.s) natively as a 32-bit Linux program, with the game faked: zones, actors,
   ObjectByName, AddSprite, SpriteSetVisible.  Built by tests/test_batch14.py (gcc -m32 -nostdlib), skipped without it. */
#include "bzcode.h"
typedef unsigned int u32;
static unsigned char sec[0x2000] __attribute__((aligned(4096)));
u32 saved_esp, result, called_init_back;
static int fails;
static void sys_write(const char*s,int n){ int r; __asm__ volatile("int $0x80":"=a"(r):"a"(4),"b"(1),"c"(s),"d"(n):"memory"); }
static int slen(const char*s){int n=0;while(s[n])n++;return n;}
static void puts_(const char*s){sys_write(s,slen(s));sys_write("\n",1);}
static void putn(u32 v){char b[12];int i=11;b[i]=0;do{b[--i]='0'+v%10;v/=10;}while(v);sys_write(b+i,11-i);}
static int seq(const char*a,const char*b){while(*a&&*a==*b){a++;b++;}return *a==*b;}
/* the game's side, faked */
static unsigned char zones[6][0x200], actors[6][0x80];
static int present[6];
static const char* names[6]={"bombZone","bombZone_B","bombZone_C","bombZone_D","bombZone_E","x"};
static int vis[64]; static int nsprites; static int obn_calls;
u32 __attribute__((cdecl)) f_obn(u32*cs){ const char*n=(const char*)cs[0]; obn_calls++;
  for(int k=1;k<6;k++) if(seq(n,names[k])) return present[k]?(u32)zones[k]:0; return 0; }
u32 __attribute__((cdecl)) f_add(u32*cs,int x,int y,int w,int h,int l,float a,float b,float c,float d){
  const char*n=(const char*)cs[0]; if(!seq(n,"armas_grupo_345.tex")||cs[1]!=20||l!=8||w!=31||h!=31){puts_("bad AddSprite args");fails++;}
  vis[nsprites]=1; return 100+nsprites++; }
void __attribute__((cdecl)) f_ssv(int id,int v){ vis[id-100]=v&0xff; }
void __attribute__((cdecl)) f_conv(int x,int y,int*ox,int*oy,int a,int b){ *ox=x; *oy=y; }
/* the minimap: actors are 3 floats (a position), the radar records its target */
static float actpos[6][4], ppos[4]; static u32 player[0x40]; static u32 mainchar;
static char radar_name[40]; static int radar_calls, radar_cleared;
u32 __attribute__((cdecl)) f_agp(u32 actor){ return actor; }
float __attribute__((cdecl)) f_dist(float*a,float*b){ float dx=a[0]-b[0],dy=a[1]-b[1],dz=a[2]-b[2]; return dx*dx+dy*dy+dz*dz; }
void __attribute__((thiscall)) f_stn(void*self,int idx,u32*cs){ const char*n=(const char*)cs[0]; int i=0; while(n[i]&&i<39){radar_name[i]=n[i];i++;} radar_name[i]=0;
  radar_calls++; if(idx!=0||cs[1]!=(u32)(i+1)){puts_("bad SetTargetName args");fails++;} }
void __attribute__((thiscall)) f_clr(void*self,int idx){ radar_cleared++; radar_name[0]=0; }
static u32 radar_obj[4];
static int nrspr, rspr_bad, rspr_seen[16];
void __attribute__((cdecl)) f_rsp(int id){ nrspr++; if(id<100||id>=116||rspr_seen[id-100]++) rspr_bad++; }
static u32 slot_rsp=(u32)f_rsp;
static u32 slot_obn=(u32)f_obn, slot_add=(u32)f_add, slot_ssv=(u32)f_ssv, slot_conv=(u32)f_conv;
static u32 slot_main=(u32)&mainchar, slot_agp=(u32)f_agp, slot_dist=(u32)f_dist, slot_stn=(u32)f_stn, slot_clr=(u32)f_clr;
static const char tex[]="armas_grupo_345.tex";
static unsigned char scene[0x700];
static u32 scene_ptr(void){ return (u32)scene; }
void win_stub(void); void nowin_stub(void); void back_stub(void);
__asm__(".globl win_stub\nwin_stub: movl $1,result\n movl saved_esp,%esp\n popa\n ret\n"
        ".globl nowin_stub\nnowin_stub: movl $2,result\n movl saved_esp,%esp\n popa\n ret\n"
        ".globl back_stub\nback_stub: movl $3,result\n movl saved_esp,%esp\n popa\n ret\n");
/* the rain: AddShower / RemoveRenderObject / ShowerSetIlumRayo, the game (CGame::main) with its shower at +0x1334 */
static unsigned char game[0x1400]; static u32 gamevar; static int showers, removed, ilum, shower_bad;
static unsigned char shw[0x100];                         /* the shower object AddShower returns (vtShower) */
#define SHW ((u32)shw)
u32 __attribute__((cdecl)) f_show(void*obj,float*pos,float w,float d,float*sp){ showers++;
  if(obj!=(void*)scene_ptr()||pos[0]!=0.0f||pos[1]!=5000.0f||pos[2]!=0.0f||w!=30000.0f||d!=30000.0f||sp[0]!=0.0f||sp[1]!=-1500.0f||sp[2]!=0.0f) shower_bad++;
  for(int i=0;i<0x100;i++) shw[i]=0x5a; return SHW; }
void __attribute__((cdecl)) f_rro(int id){ if((u32)id==SHW) removed++; else shower_bad++; }
void __attribute__((cdecl)) f_ilum(int id,int on){ if((u32)id==SHW&&(on&0xff)==1) ilum++; else shower_bad++; }
static u32 slot_show=(u32)f_show, slot_rro=(u32)f_rro, slot_ilum=(u32)f_ilum, slot_game=(u32)&gamevar;
static int nrel, nload, load_bad; static char lastname[64];
void __attribute__((cdecl)) f_rel(int h){ if(h==0) load_bad++; nrel++; }
int __attribute__((cdecl)) f_load(u32*cs,int b,float f,float g){ const char*n=(const char*)cs[0]; int i=0; while(n[i]&&i<63){lastname[i]=n[i];i++;} lastname[i]=0;
  if((u32)(i+1)!=cs[1]||(b&0xff)!=0||f!=0.0f||g!=1000000.0f) load_bad++; return 0x7000+nload++; }
static u32 slot_rel=(u32)f_rel, slot_load=(u32)f_load;
u32 dtor_eax, dtor_zf;
void dback_stub(void);
/* the scene's destructor, at its start: the hook took "mov eax,[esi+604h] / test eax,eax" - eax and ZF come back */
__asm__(".globl dback_stub\ndback_stub: movl %eax,dtor_eax\n setz %al\n movzbl %al,%eax\n movl %eax,dtor_zf\n movl $4,result\n movl saved_esp,%esp\n popa\n ret\n");
/* the splashes: the camera, its matrix / position, Random, GetHeight, AddParticleSystem, SetParticleCountDown */
static u32 camobj[0x20]; static u32 camvar; static int nparts, ncount, nheight, splash_bad, rnd_i;
static float hy_in, minx=1e9f, maxx=-1e9f, minz=1e9f, maxz=-1e9f;
float* __attribute__((cdecl)) f_vmtx(float*out,int id){ if(id!=55) splash_bad++; for(int i=0;i<16;i++) out[i]=0; out[8]=3.0f; out[9]=9.0f; out[10]=4.0f; return out; }
float* __attribute__((thiscall)) f_gcol(float*m,float*out,int idx){ if((idx&0xff)!=2) splash_bad++; out[0]=m[8]; out[1]=m[9]; out[2]=m[10]; return out; }
float* __attribute__((cdecl)) f_cpos(float*out,int id){ if(id!=55) splash_bad++; out[0]=100.0f; out[1]=50.0f; out[2]=200.0f; return out; }
float __attribute__((cdecl)) f_sint(int id){ if((u32)id!=SHW) splash_bad++; return 0.5f; }
float __attribute__((cdecl)) f_rand(void){ static const float r[]={0.0f,0.25f,0.5f,0.75f,0.999f,0.1f}; return r[(rnd_i++)%6]; }
char __attribute__((cdecl)) f_gh(float*in,float*out){ nheight++; hy_in=in[1];
  if(in[0]<minx)minx=in[0]; if(in[0]>maxx)maxx=in[0]; if(in[2]<minz)minz=in[2]; if(in[2]>maxz)maxz=in[2];
  out[0]=in[0]; out[1]=7.0f; out[2]=in[2]; return (nheight%3)!=0; }
u32 __attribute__((cdecl)) f_aps(void*scn,u32*cs,float*at,float*up,float a5,float a6,float a7,float a8,float a9,float a10,
    float*grav,float a12,u32 c13,u32 c14,float a15,float a16,float a17,float a18,u32 f19,int a20){
  const char*n=(const char*)cs[0];
  if(scn!=(void*)scene_ptr()||!seq(n,"gota_salpica.tex")||cs[1]!=17||at[1]!=7.0f||up[1]!=300.0f||grav[1]!=-1700.0f||a5!=-0.5f||
     a6!=0.6f||a7!=0.0f||a8!=3.0f||a9!=20.0f||a10!=0.2f||a12!=0.97f||c13!=0xff000000u||c14!=0xb7000000u||a15!=10.0f||a16!=10.0f||
     a17!=1.0f||a18!=100000.0f||f19!=0x91000004u||a20!=0) splash_bad++;
  return 500+nparts++; }
void __attribute__((cdecl)) f_spcd(int id,int t){ if(id<500||t!=7) splash_bad++; ncount++; }
static u32 slot_cam=(u32)&camvar, slot_vmtx=(u32)f_vmtx, slot_gcol=(u32)f_gcol, slot_cpos=(u32)f_cpos, slot_sint=(u32)f_sint,
  slot_rand=(u32)f_rand, slot_gh=(u32)f_gh, slot_aps=(u32)f_aps, slot_spcd=(u32)f_spcd;
u32 rb_esi, rb_m4c, rb_zf, rb_regs[3], run_eax;
void rback_stub(void); void enter_run(void);
__asm__(".globl rback_stub\nrback_stub: setz %al\n movzbl %al,%eax\n movl %eax,rb_zf\n movl %esi,rb_esi\n movl 0x4c(%esp),%eax\n movl %eax,rb_m4c\n"
        " movl (%esp),%eax\n movl %eax,rb_regs\n movl 12(%esp),%eax\n movl %eax,rb_regs+4\n movl $5,result\n movl saved_esp,%esp\n popa\n ret\n"
        ".globl enter_run\nenter_run: pusha\n movl %esp,saved_esp\n movl entry_esi,%ecx\n movl $0x1111,%ebx\n movl $0x2222,%ebp\n movl $0x3333,%esi\n"
        " movl $0x4444,%edi\n movl run_eax,%eax\n subl $0x120,%esp\n testl %eax,%eax\n jmp *entry_addr\n");
u32 entry_edi, entry_esi, entry_addr;
void enter(void);
__asm__(".globl enter\nenter: pusha\n movl %esp,saved_esp\n movl entry_edi,%edi\n movl entry_esi,%esi\n"
        " movl $0xdead,%eax\n subl $0x120,%esp\n jmp *entry_addr\n");
static void P(u32 off,u32 v){*(u32*)(sec+0x800+off)=v;}
static int run(u32 off){ entry_addr=(u32)sec+off; entry_edi=present[0]?(u32)zones[0]:0; entry_esi=(u32)scene; result=0; enter(); return result; }
#define CHECK(c,msg) do{ if(!(c)){ puts_(msg); fails++; } }while(0)
void _start(void){
  __asm__ volatile("int $0x80"::"a"(125),"b"((u32)sec),"c"(0x2000),"d"(7));   /* mprotect RWX */
  for(u32 i=0;i<sizeof(CODE);i++) sec[i]=CODE[i];
  u32 init=*(u32*)(sec+0x7f0);
  P(0x00,(u32)win_stub-(u32)sec); P(0x04,(u32)nowin_stub-(u32)sec); P(0x08,(u32)back_stub-(u32)sec);
  P(0x0c,(u32)&slot_obn-(u32)sec); P(0x10,(u32)&slot_add-(u32)sec); P(0x14,(u32)&slot_ssv-(u32)sec); P(0x18,(u32)&slot_conv-(u32)sec);
  P(0x1c,(u32)tex-(u32)sec); P(0x2c,20);
  for(int k=0;k<6;k++){ P(0x30+4*k,slen(names[k])+1); for(int j=0;names[k][j];j++) sec[0x860+32*k+j]=names[k][j];
     *(u32*)(zones[k]+0x164)=(u32)actors[k]; *(u32*)(zones[k]+0xa0)=(u32)actpos[k]; actpos[k][0]=1000.0f*k;
     *(float*)(zones[k]+0x160)=300.0f; }
  P(0x4c,(u32)&slot_main-(u32)sec); P(0x50,(u32)&slot_agp-(u32)sec); P(0x54,(u32)&slot_dist-(u32)sec);
  P(0x58,(u32)&slot_stn-(u32)sec); P(0x5c,(u32)&slot_clr-(u32)sec); P(0x48,0);
  *(u32*)(scene+0x268)=(u32)radar_obj; player[0xa0/4]=(u32)ppos;
  /* any mode, 3 zones */
  P(0x20,0); P(0x24,1); P(0x28,3); present[0]=present[1]=present[2]=1;
  *(u32*)(scene+0x630)=2;
  CHECK(run(init)==3,"init did not come back"); CHECK(nsprites==6,"init: 6 sprites");
  CHECK(vis[0]==1&&vis[1]==0&&vis[2]==1&&vis[3]==0,"init: destroyed icons hidden");
  CHECK(run(0)==2,"any: nothing destroyed -> nowin");
  zones[1][0x178]=1; CHECK(run(0)==1,"any: B exploding -> win");
  CHECK(vis[2]==0&&vis[3]==1&&vis[0]==1,"hud: B shows destroyed");
  zones[1][0x178]=0; actors[1][0x64]=1; CHECK(run(0)==1,"any: B destroyed (model) -> win");
  /* all mode */
  P(0x20,1); actors[1][0x64]=0;
  CHECK(run(0)==2,"all: none");
  zones[0][0x178]=1; CHECK(run(0)==2,"all: A exploding only");
  zones[0][0x178]=0; actors[0][0x64]=1; zones[1][0x178]=1; CHECK(run(0)==2,"all: A destroyed, B exploding, C intact");
  present[2]=0; CHECK(run(0)==1,"all: C not in the scene -> A+B win");
  present[2]=1; actors[2][0x64]=1; zones[1][0x178]=0; actors[1][0x64]=1; CHECK(run(0)==1,"all: all three destroyed");
  CHECK(vis[1]==1&&vis[0]==0&&vis[5]==1&&vis[4]==0,"hud: all destroyed icons");
  present[0]=0; CHECK(run(0)==2,"all: no bombZone -> nowin");
  /* the minimap: the nearest zone still standing (A at x=0, B at 1000, C at 2000) */
  for(int k=0;k<3;k++){ zones[k][0x178]=0; actors[k][0x64]=0; } present[0]=present[1]=present[2]=1; P(0x20,1);
  P(0x48,1); mainchar=0; run(0); CHECK(radar_calls==0,"radar: no local player, nothing");
  mainchar=(u32)player; ppos[0]=900.0f; run(0); CHECK(seq(radar_name,"bombZone_B"),"radar: near B -> B");
  run(0); CHECK(radar_calls==1,"radar: set once, not every frame");
  actors[1][0x64]=1; run(0); CHECK(seq(radar_name,"bombZone"),"radar: B destroyed -> A (nearer than C)");
  ppos[0]=1600.0f; run(0); CHECK(seq(radar_name,"bombZone_C"),"radar: nearer C -> C");
  actors[0][0x64]=1; actors[2][0x64]=1; run(0); CHECK(radar_cleared==1&&radar_name[0]==0,"radar: all destroyed -> cleared");
  /* a destroyed zone takes no second bomb: radius 0 while destroyed, back once it stands again (the round's reset) */
  for(int k=0;k<3;k++){ zones[k][0x178]=0; actors[k][0x64]=0; }
  run(0); CHECK(*(float*)(zones[1]+0x160)==300.0f&&*(float*)(zones[0]+0x160)==300.0f,"radius: intact zones have theirs (back after the radar tests)");
  zones[1][0x178]=1; run(0); CHECK(*(u32*)(zones[1]+0x160)==0&&*(float*)(zones[0]+0x160)==300.0f,"radius: B exploding -> 0");
  zones[1][0x178]=0; actors[1][0x64]=1; run(0); CHECK(*(u32*)(zones[1]+0x160)==0,"radius: B destroyed -> stays 0");
  actors[1][0x64]=0; run(0); CHECK(*(float*)(zones[1]+0x160)==300.0f,"radius: B reset -> 300 again");
  run(0); CHECK(*(float*)(zones[1]+0x160)==300.0f,"radius: put back once");
  for(int k=0;k<3;k++) actors[k][0x64]=0;
  *(u32*)(scene+0x630)=0; int before=radar_calls; ppos[0]=1900.0f; run(0); CHECK(radar_calls==before,"radar: plaza-type left alone");
  *(u32*)(scene+0x630)=2; P(0x48,0); run(0); CHECK(radar_calls==before,"radar: off");
  P(0x48,1); run(0); before=radar_calls; run(0); CHECK(radar_calls==before,"radar: steady");
  run(*(u32*)(sec+0x7f0)); run(0); CHECK(radar_calls==before+1,"radar: a new scene (init) sets it again");
  /* init not for plaza-type scenes, nor without HUD */
  present[0]=1; nsprites=0; *(u32*)(scene+0x630)=0; CHECK(run(init)==3&&nsprites==0,"init: plaza type makes no icons");
  *(u32*)(scene+0x630)=2; P(0x24,0); CHECK(run(init)==3&&nsprites==0,"init: no HUD");
  /* the icons off the screen at the scene's end (they stayed in the next map) */
  { u32 dtor=*(u32*)(sec+0x7f8); P(0x130,(u32)dback_stub-(u32)sec); P(0x24,1); P(0x1e0,(u32)&slot_rsp-(u32)sec);
    nsprites=0; CHECK(run(init)==3&&nsprites==6,"icons: 3 pairs");
    CHECK(run(dtor)==4&&nrspr==6&&rspr_bad==0,"icons: all 6 removed at the end");
    CHECK(run(dtor)==4&&nrspr==6,"icons: removed once");
    *(u32*)(scene+0x630)=0; nsprites=0; run(init); CHECK(run(dtor)==4&&nrspr==6,"icons: none made, none removed");
    *(u32*)(scene+0x630)=2; P(0x24,0); P(0x1e0,0); }
  /* the rain: made at the scene's start (any DO type), kept by the game, thrown away at the scene's end */
  { u32 dtor=*(u32*)(sec+0x7f8);
    P(0x12c,(u32)&slot_game-(u32)sec); P(0x124,(u32)&slot_show-(u32)sec); P(0x128,(u32)&slot_rro-(u32)sec); P(0x13c,(u32)&slot_ilum-(u32)sec);
    P(0x130,(u32)dback_stub-(u32)sec); *(float*)(sec+0x800+0x134)=30000.0f;
    float*rp=(float*)(sec+0x800+0x140); rp[0]=0; rp[1]=5000.0f; rp[2]=0; float*rs=(float*)(sec+0x800+0x150); rs[0]=0; rs[1]=-1500.0f; rs[2]=0;
    gamevar=(u32)game; P(0x120,0); P(0x24,0);
    CHECK(run(init)==3&&showers==0,"rain off: no shower");
    CHECK(run(dtor)==4&&removed==0,"rain off: dtor removes nothing");
    *(u32*)(scene+0x604)=0x6040; CHECK(run(dtor)==4&&dtor_eax==0x6040&&dtor_zf==0,"dtor: the two lines it took");
    *(u32*)(scene+0x604)=0; CHECK(run(dtor)==4&&dtor_eax==0&&dtor_zf==1,"dtor: the two lines it took (0: ZF)");
    P(0x120,1); P(0x138,0); *(u32*)(scene+0x630)=0;
    CHECK(run(init)==3&&showers==1&&*(u32*)(game+0x1334)==SHW&&ilum==0,"rain: AddShower, kept in CGame+0x1334");
    CHECK(shw[0xe8]==0x5a&&shw[0xb4]==0x5a&&shw[0xc8]==0x5a,"storm: the shower as it is");
    CHECK(shower_bad==0,"rain: Marbella's arguments");
    *(u32*)(scene+0x604)=0x6041; dtor_eax=0; CHECK(run(dtor)==4&&removed==1&&*(u32*)(game+0x1334)==0,"rain: removed at the end");
    CHECK(dtor_eax==0x6041&&dtor_zf==0,"rain dtor: the two lines it took");
    CHECK(run(dtor)==4&&removed==1,"rain: removed once");
    P(0x138,1); CHECK(run(init)==3&&showers==2&&ilum==0,"calm: made");
    { int ok=shw[0xe8]==0&&shw[0xb0]==0x5a; for(int o=0xb4;o<0xcc;o++) ok&=shw[o]==0; CHECK(ok,"calm: no flashes, no thunder, its rain sound kept"); }
    P(0x138,0);
    /* calm with ReleaseSound: the six thunders released, not only emptied; the map's quieter sounds loaded instead */
    P(0x1e8,(u32)&slot_rel-(u32)sec); P(0x1e4,(u32)&slot_load-(u32)sec);
    run(dtor); P(0x138,1); nrel=nload=0; CHECK(run(init)==3&&nrel==6&&nload==0,"calm: the six thunders released");
    { const char*a="wavs/mp_x_LLUVIA_2.wav"; const char*b="wavs/mp_x_trueno.wav"; int la=slen(a),lb=slen(b);
      *(u32*)(sec+0xc00)=la+1; for(int j=0;j<la;j++) sec[0xc04+j]=a[j]; *(u32*)(sec+0xc40)=lb+1; for(int j=0;j<lb;j++) sec[0xc44+j]=b[j]; }
    P(0x138,0); run(dtor); nrel=nload=0; CHECK(run(init)==3&&nrel==2&&nload==2,"sounds: two replaced");
    CHECK(*(u32*)(shw+0xb0)==0x7000&&*(u32*)(shw+0xb4)==0x7001&&*(u32*)(shw+0xb8)==0x5a5a5a5au&&seq(lastname,"wavs/mp_x_trueno.wav"),"sounds: in their places, the others kept");
    P(0x138,1); run(dtor); nrel=nload=0; CHECK(run(init)==3&&nload==1&&*(u32*)(shw+0xb0)==0x7000&&*(u32*)(shw+0xb4)==0,"calm + sounds: the rain's only");
    CHECK(load_bad==0,"LoadSound: vtShower's arguments");
    P(0x138,0); P(0x1e8,0); P(0x1e4,0); *(u32*)(sec+0xc00)=0; *(u32*)(sec+0xc40)=0;
    run(dtor); gamevar=0; CHECK(run(init)==3&&showers==6,"no game: shower made, not kept"); CHECK(run(dtor)==4&&removed==5,"no game: dtor fine");
    CHECK(shower_bad==0,"rain: arguments");
    /* the splashes, every frame from the scene's Run */
    u32 sp=*(u32*)(sec+0x7e0), spret=*(u32*)(sec+0x7e4);
    *(u32*)(sec+spret+1)=(u32)rback_stub-((u32)sec+spret+5);
    P(0x164,(u32)&slot_cam-(u32)sec); P(0x168,(u32)&slot_vmtx-(u32)sec); P(0x16c,(u32)&slot_gcol-(u32)sec);
    P(0x170,(u32)&slot_cpos-(u32)sec); P(0x174,(u32)&slot_sint-(u32)sec); P(0x178,(u32)&slot_rand-(u32)sec);
    P(0x17c,(u32)&slot_gh-(u32)sec); P(0x180,(u32)&slot_aps-(u32)sec); P(0x184,(u32)&slot_spcd-(u32)sec);
    const char*t2="gota_salpica.tex"; for(int j=0;t2[j];j++) sec[0x990+j]=t2[j]; P(0x1a4,17);
    float*fp=(float*)(sec+0x9a8); fp[0]=2000.0f; fp[1]=4000.0f; fp[2]=0.5f; fp[3]=20.0f;
    float*up=(float*)(sec+0x9c0); up[0]=0; up[1]=300.0f; up[2]=0; float*gv=(float*)(sec+0x9d0); gv[0]=0; gv[1]=-1700.0f; gv[2]=0;
    camobj[0x38/4]=55; camvar=(u32)camobj; gamevar=(u32)game; *(u32*)(game+0x1334)=SHW; P(0x120,1);
    entry_esi=(u32)scene; entry_addr=(u32)sec+sp;
    P(0x160,0); run_eax=(u32)player; result=0; enter_run();
    CHECK(result==5&&nparts==0&&rb_esi==(u32)scene&&rb_m4c==(u32)player&&rb_zf==0,"splash off: the lines it took, nothing else");
    CHECK(rb_regs[0]==0x4444&&rb_regs[1]==0x1111,"splash: the 4 pushes");
    P(0x160,1); run_eax=0; result=0; enter_run(); CHECK(result==5&&nparts==0&&rb_zf==1,"no local player: no splashes, flags kept");
    run_eax=(u32)player; result=0; enter_run();
    CHECK(result==5&&nheight==10,"splash: intensity 0.5 x 20 = 10 drops");
    CHECK(nparts==7&&ncount==7,"splash: one burst per drop that meets the floor (GetHeight)");
    CHECK(hy_in==2050.0f,"splash: drops 2000 above the camera");
    CHECK(minx>=1300.0f-2000.0f-1&&maxx<=1300.0f+2000.0f+1&&minz>=1800.0f-2000.0f-1&&maxz<=1800.0f+2000.0f+1&&maxx-minx>2500.0f&&maxz-minz>3900.0f&&minx<0.0f,
          "splash: a 4000 square 2000 ahead of the camera (forward 0.6, 0.8 on the ground)");
    CHECK(splash_bad==0,"splash: mp_deathMatch's arguments");
    *(u32*)(game+0x1334)=0; int before2=nparts; enter_run(); CHECK(nparts==before2,"splash: no rain, no splashes");
    camvar=0; *(u32*)(game+0x1334)=SHW; enter_run(); CHECK(nparts==before2&&result==5,"splash: no camera"); }
  puts_(fails?"FAILED":"all ok"); putn(fails); sys_write("\n",1);
  __asm__ volatile("int $0x80"::"a"(1),"b"(fails));
}
