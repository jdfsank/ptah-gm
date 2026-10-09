#!/usr/bin/env python3
"""Explicit Velvet Eclipse snapshot adapter; not a universal GDScript parser.
Reads the specified source tree, emits evidence-backed semantic data to this Site.
Reviewed numeric anchors require a complete numeric token. A saved source hash lock
requires a fresh review if any inventoried source changes. Game is read-only.
"""
import argparse, hashlib, html, json, re, shutil
from pathlib import Path
P=argparse.ArgumentParser();P.add_argument('source');P.add_argument('--out',default='dist');P.add_argument('--accept-reviewed-source',action='store_true',help='Explicitly refresh the reviewed hash lock after manual source review');a=P.parse_args()
root=Path(a.source).resolve();lock=Path(__file__).with_name('velvet-source-lock.json')
if lock.exists() and not a.accept_reviewed_source:
 for item in json.loads(lock.read_text()):
  path=root/item['path']
  if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Source changed; re-review before --accept-reviewed-source: '+item['path'])
out=Path(a.out).resolve();out.mkdir(exist_ok=True)
files={};sources=[];refs={};ledger=[];objects=[];instances=[];spawn_rules=[]
def read(path):
 if path not in files: files[path]=(root/path).read_text()
 return files[path]
def ref(path,needle=None):
 text=read(path);lines=text.splitlines();line=1
 if needle is not None:
  pattern=re.escape(needle)+(r'(?![\d.])' if needle[-1:].isdigit() else '')
  hit=[i+1 for i,l in enumerate(lines) if re.search(pattern,l)]
  if not hit:raise ValueError(f'Reviewed anchor missing: {path}: {needle}')
  line=hit[0]
 key=f'{path}:{line}'
 if key not in refs:
  sid='source:'+str(len(sources)+1);refs[key]=sid
  sources.append(dict(id=sid,path=path,line=line,sha256=hashlib.sha256((root/path).read_bytes()).hexdigest(),url='evidence/'+path+'.html#L'+str(line)))
 return refs[key]
def status(edit='read-only',impl='implemented',mapping='reviewed-source',verification='static-source'):
 return dict(implementation=impl,mapping=mapping,editability=edit,verification=verification)
def b(id,label,type,summary,paths,states=(),motion=None,clips=(),params=None,limitations=()):
 rs=[ref(*p) if isinstance(p,tuple) else ref(p) for p in paths]
 return dict(id=id,label=label,type=type,summary=summary,states=list(states),motion=motion,presentation=dict(clips=list(clips)),parameters=params or {},limitations=list(limitations),sourceRefs=rs,evidence='fact',status=status('browser-draft' if params and any(p.get('editable') for p in params.values()) else 'read-only'))
def param(value,label,unit,path,needle,editable=False,max=6):
 return dict(value=value,label=label,unit=unit,evidence='fact',sourceRefs=[ref(path,needle)],editable=editable,min=0,max=max)
def obj(id,label,kind,body,drivers,paths,behaviors=(),asset=None,limitations=(),relations=()):
 rs=[ref(*p) if isinstance(p,tuple) else ref(p) for p in paths]
 o=dict(id=id,label=label,kind=kind,layer='definition',body=body,drivers=drivers,behaviors=list(behaviors),asset=asset,sourceRefs=rs,evidence='fact',status=status(),limitations=list(limitations),relations=list(relations),facets={'design':{'text':body,'evidence':'fact','sourceRefs':rs},'narrative':None,'art':{'asset':asset,'evidence':'fact','sourceRefs':rs} if asset else None})
 objects.append(o);return o
MS='scripts/systems/movement_system.gd';CS='scripts/systems/combat_system.gd';AS='scripts/systems/animation_system.gd';AI='scripts/systems/enemy_ai_system.gd';BS='scripts/systems/boss_system.gd';DS='scripts/systems/damage_system.gd';IS='scripts/systems/interaction_system.gd';PS='scripts/systems/progression_system.gd';RT='scripts/runtime/game_runtime.gd';EF='scripts/runtime/entity_factory.gd';CM='scripts/components/c_motion.gd';RC='scripts/runtime/resource_catalog.gd'
# These expected facts are deliberately asserted at their reviewed source anchors.
move=b('player.move','地面连续移动','continuous','A/D 或方向键给出轴值，驱动目标速度与加减速。源代码没有独立 walk/run 切换或持续 sprint。',[CM,MS,(AS,'absf(motion.velocity.x) > 8.0')],['grounded','airborne'],{'kind':'velocity','writer':'MovementSystem','description':'target vx = axis × speed；以 acceleration 接近目标。动画 run/idle 按实际速度切换。'},['heroine_frames/run','heroine_frames/idle'],{
 'speed':param(300,'最大水平速度','px/s',CM,'speed: float = 300.0',True,2000), 'acceleration':param(2400,'加速度','px/s²',CM,'acceleration: float = 2400.0',True,10000)})
jump=b('player.jump','跳跃与月步扩展','action','按下 jump 进入缓冲；地面/土狼时间允许首跳，已获月步且 jumps_used<2 允许空中追加跳。',[MS,CM,PS],['buffered','first-jump','air-jump','airborne','grounded'],{'kind':'ballistic','writer':'MovementSystem','description':'首跳 / 月步设 vy = −580；重力 1500，落速上限 900；落地重置 jumps_used。'},['heroine_frames/jump'],{
 'jumpSpeed':param(580,'跳跃初速度','px/s',CM,'jump_speed: float = 580.0'),'coyote':param(.10,'土狼时间','s',CM,'coyote_duration: float = 0.10'),'buffer':param(.12,'输入缓冲','s',CM,'buffer_duration: float = 0.12')})
fall=b('player.fall-land','下落 / 落地','response','重力与地面接触自动触发。空中共享 jump 表现；落地重置跳跃次数，并按水平速度回到 run/idle。',[MS,AS],['airborne','grounded'],{'kind':'physics','writer':'MovementSystem','description':'无独立 fall 或 land 动作开关。'},['heroine_frames/jump','heroine_frames/run','heroine_frames/idle'],limitations=['没有独立 fall / land 剪辑。'])
sword=b('player.sword','剑击','action','J 触发，共享状态机生成独立命中盒与 slash 效果。浏览器可改时序草稿，不会修改源冷却/动画/命中。',[CS,'scripts/components/c_combat.gd'],['idle','sword_windup','sword_active','sword_recovery','idle'],None,['heroine_frames/attack'],{
 'front':param(.10,'前摇','s',CS,'combat.time_left = 0.1',True,2),'active':param(.14,'命中生效','s',CS,'combat.time_left = 0.14',True,2),'recovery':param(.16,'后摇','s',CS,'combat.time_left = 0.16',True,2),
 'vfxStart':dict(value=.10,label='VFX 开始（相对动作）',unit='s',evidence='inference',sourceRefs=[ref(CS,'_sword(entity, combat)')],editable=True,min=0,max=6),
 'vfxDuration':param(.20,'VFX 持续','s',CS,'"duration": 0.2,',True,6),'cooldown':param(.42,'源冷却','s',CS,'combat.sword_cooldown = 0.42')},['VFX 相对开始由生成时机推导；浏览器字段不是源生独立时间轴。','VFX 0.20 秒与命中盒 0.14 秒互不等同。'])
cast=b('player.cast','魔法纸牌','action','K 在空闲、冷却完成且能量足够时扣能量；前摇后生成投射物，再恢复。',[CS,'scripts/components/c_combat.gd'],['idle','cast_windup','cast_recovery','idle'],None,['heroine_frames/cast'],{'windup':param(.12,'前摇','s',CS,'combat.time_left = 0.12'),'recovery':param(.24,'恢复','s',CS,'combat.time_left = 0.24'),'cooldown':param(.46,'冷却','s',CS,'combat.card_cooldown = 0.46'),'cost':param(25,'能量消耗','点','scripts/components/c_combat.gd','card_cost: float = 25.0')},['能量不足不会进入施法；不等于缺失输入。'])
dodge=b('player.dodge','闪避 · 短冲刺','action','Shift/L 触发短冲刺；0.22 秒持续，0.85 秒冷却，最后 0.04 秒无闪避无敌。',[MS,CS],['idle','dodge','idle'],{'kind':'burst','writer':'MovementSystem','description':'横向速度固定为 facing × 720，非持续 sprint 模式。'},['heroine_frames/dodge'],{'speed':param(720,'短冲刺速度','px/s',MS,'motion.facing * 720.0'),'duration':param(.22,'持续','s',CS,'combat.time_left = 0.22'),'cooldown':param(.85,'冷却','s',CS,'combat.dodge_cooldown = 0.85'),'vulnerableTail':param(.04,'末段非无敌','s',CS,'combat.time_left > 0.04')})
hurt=b('player.hurt','受伤','response','合法敌对命中且非无敌时减血；打断非首领战斗，短暂受伤后恢复。',[DS,CS,AS],['hit','hurt','recover'],None,['heroine_frames/hurt'],{'duration':param(.28,'受伤状态','s',DS,'health.hurt_left = 0.28'),'invulnerability':param(.45,'玩家受伤保护','s',DS,'0.45 if health.team')})
death=b('player.death','死亡与重试','response','HP 降至 0 后转死亡会话，提供重试流程。死亡后动画暂停，不承诺完整自动淡出；不存在独立 death 剪辑。',[DS,PS,AS,RT],['alive','dead','death-screen','retry'],None,[],limitations=['无 death 剪辑；不能把淡出称为完整死亡动画。'])
interact=b('player.interact','交互','interaction','E 提交当前最近且可用的门、遗物或存档点。未选中/不可用时无操作。',[IS,'scripts/systems/input_system.gd'],['candidate','available','selected','activate'],None,[],limitations=['交互是目标/条件/结果关系，不是角色专用动画。'])
obj('actor.player','女主角 · 玩家定义','actor','跨房间存续的单一 Player；房间 start/from_* 仅定位。',['player','physics','event'],[(EF,'func create_player')],[move,jump,fall,dodge,sword,cast,hurt,death,interact],'heroine',relations=['rule.health','rule.session','progression.moonstep'])
for kind,label,speed,attack,asset in [('melee','骷髅荷官 · 近战',105,85,'dealer'),('ranged','幽灵荷官 · 远程',90,380,'dealer'),('flying','飞行纸牌',125,190,'enemy_card')]:
 clips=[] if kind=='flying' else ['dealer_frames/idle','dealer_frames/move','dealer_frames/cast' if kind=='ranged' else 'dealer_frames/melee_attack']
 states=['spawning','idle','approach']+(['retreat'] if kind=='ranged' else [])+['telegraph']+(['lunge'] if kind=='flying' else [])+['recover']
 desc={'melee':'进入感知范围后水平接近；近距离且垂直差 <75 时预警后剑击。','ranged':'距离过近（|dx|<220）先后退；进入攻击范围后预警并施放纸牌。','flying':'无重力，二维接近偏移目标；预警后剑击并沿朝向突进，再恢复。'}[kind]
 params={'speed':param(speed,'接近速度','px/s',EF,f'motion.speed = {speed}.0'),'aggro':param(430,'工厂感知距离','px',EF,'ai.aggro_range = 430.0'),'spawnDelay':param(1,'出场等待','s',EF,'ai.time_left = 1.0'),'hp':param(60,'生命','HP',EF,'health.maximum = 60')}
 params['attackRange']=param(attack,'攻击水平距离','px','scripts/components/c_enemy_ai.gd' if kind=='melee' else EF,'attack_range: float = 85.0' if kind=='melee' else f'ai.attack_range = {attack}.0')
 if kind=='flying':params['lungeSpeed']=param(360,'突进目标速度','px/s',AI,'motion.facing * 360.0')
 obj('actor.enemy.'+kind,label,'actor','AI 驱动的独立敌人原型；共享资源不等于共享行为。',['AI','time','physics'],[(EF,'func create_enemy'),AI],[
 b('enemy.'+kind+'.ai','感知 / 移动 / 攻击','continuous',desc,[AI,EF],states,{'kind':'steering','writer':'MovementSystem','description':desc},clips,params,['patrol_radius/home 已存储，但 AI 没有巡逻往返实现。','无效/死亡/跨房间目标、自身受伤或待放置时停止决策。']),
 b('enemy.'+kind+'.hurt-death','受伤与消失','response','受伤中停止 AI；生命归零后淡出，hurt_left 结束后移除。',[DS,AS,AI],['alive','hurt','dead','removed'],None,[] if kind=='flying' else ['dealer_frames/idle'],limitations=['没有独立敌人 hurt/death 剪辑。飞行牌仅静态贴图、翻转和速度相关旋转。' if kind=='flying' else '受伤选 idle + 染色；死亡无专用剪辑。'])],asset,limitations=['该工作台只读展示源 AI，不运行寻路/战斗/物理。'])
obj('actor.boss','Royal Dealer · 首领','actor','房间内自动激活的两阶段首领；motion.speed=0，无行走策略。',['AI','time','event'],[(EF,'func create_boss'),BS],[
 b('boss.cycle','战斗循环与阶段','rule','playing 且同处王座房间时激活；生命减半进入第二阶段，清临时对象并修改背景色。',[BS,CS],['idle','fan_warning','fan_attack','slam_warning','slam_attack','recovery','phase_change'],{'kind':'stationary','writer':'MovementSystem','description':'位置不由 AI 导航改变；只改变朝向，仍拥有重力/碰撞组件。'},['boss_frames/idle','boss_frames/attack'],{'hp':param(1400,'生命','HP',EF,'health.maximum = 1400'),'phaseChange':param(1.4,'换阶段停顿','s',BS,'boss.time_left = 1.4')},['房间判断代替独立 arena 几何触发；room.boss.arena 元数据没有作为触发区使用。','只绑定 idle/attack；无独立移动/受伤/死亡剪辑。']),
 b('boss.defeat','击败与结局','response','生命归零，进度记录 boss_defeated 并切换结局；敌对临时对象停止。',[PS,DS,RT],['alive','dead','ending'],None,[],limitations=['没有已实现的独立死亡动画。'])],'boss')
# Separate discrete attacks from continuous autonomous steering, retaining shared source evidence.
for kind in ['melee','ranged','flying']:
 o=next(o for o in objects if o['id']=='actor.enemy.'+kind)
 o['behaviors'][0]['label']='感知与运动决策'
 attack_params={'telegraph':param(.65 if kind=='ranged' else .5,'AI 预警','s',AI,'ai.time_left = 0.65 if ai.kind'),
  'front':param(.12 if kind=='ranged' else .10,'战斗前摇','s',CS,'combat.time_left = 0.12' if kind=='ranged' else 'combat.time_left = 0.1'),
  'recovery':param(.24 if kind=='ranged' else .16,'战斗恢复','s',CS,'combat.time_left = 0.24' if kind=='ranged' else 'combat.time_left = 0.16')}
 if kind=='ranged':attack_params['speed']=param(320,'纸牌速度','px/s',CS,'"speed": 660.0 if health.team');attack_params['damage']=param(10,'伤害','HP',CS,'"damage": 20 if health.team')
 else:attack_params['active']=param(.14,'命中盒生效','s',CS,'"active_left": 0.14');attack_params['damage']=param(12,'伤害','HP',CS,'"damage": 25 if health.team')
 o['behaviors'].insert(1,b('enemy.'+kind+'.attack','投掷纸牌' if kind=='ranged' else '突进剑击' if kind=='flying' else '近战剑击','action','AI 预警完成后请求共享 CombatSystem 动作。AI recover/lunge 计时与战斗前摇/恢复是两个状态域，不能相加当成同一动画时长。',[AI,CS],['telegraph','attack-request','combat-windup','active-or-spawn','combat-recovery'],None,[] if kind=='flying' else ['dealer_frames/cast' if kind=='ranged' else 'dealer_frames/melee_attack'],attack_params,['本概念不执行敌人攻击或命中。']))
boss=next(o for o in objects if o['id']=='actor.boss')
boss['behaviors'].insert(1,b('boss.fan','扇形纸牌','action','预警结束后，CombatSystem 再经过 0.35 秒前摇发射。第一/二阶段为 3/5 张，第二阶段扇形后衔接砸击。',[BS,CS],['fan_warning','boss_fan_windup','fan_attack','boss_recovery'],None,['boss_frames/attack'],{'windup':param(.35,'战斗前摇','s',CS,'combat.time_left = 0.35'),'phaseOneSpeed':param(270,'阶段一速度','px/s',CS,'"speed": 270.0 if boss.phase'),'phaseTwoSpeed':param(350,'阶段二速度','px/s',CS,'"speed": 270.0 if boss.phase'),'damage':param(12,'每张伤害','HP',CS,'"damage": 12, "remaining": 4.5'),'lifetime':param(4.5,'投射物寿命','s',CS,'"remaining": 4.5')}))
boss['behaviors'].insert(2,b('boss.slam','幽灵之手砸击','action','锁定玩家当时的 x（限制 120..1480），目标 y=592；预警 + 战斗前摇后产生固定命中盒。幽灵之手是视觉提示，不是伤害本体。',[BS,CS],['slam_warning','boss_slam_windup','slam_attack','boss_recovery'],None,['boss_frames/attack'],{'active':param(.18,'命中盒生效','s',CS,'"active_left": 0.18'),'damage':param(22,'伤害','HP',CS,'"damage": 22, "active_left"'),'effect':param(.30,'冲击效果','s',CS,'"duration": 0.3,')}))
sword['presentation']['timeline']={'phases':[{'key':'front','label':'前摇','class':'front'},{'key':'active','label':'生效','class':'active'},{'key':'recovery','label':'后摇','class':'recover'}],'effect':{'start':'vfxStart','duration':'vfxDuration'},'actorAsset':'heroine','targetAsset':'dealer','fieldPrefix':'attack'}
# Semantic environmental, nonentity and shared-support concepts.
specs=[
 ('env.platform','碰撞平台','environment','静态碰撞结构，左/中/右资源组合；当前源没有移动平台。',['physics'],[EF,'scripts/systems/materialization_system.gd'],'platform_middle','platform.support','站立与阻挡','response','碰撞由引擎完成；浏览器只做矩形编排。',['static','contact']),
 ('env.decor','场景装饰 / 背景','environment','共享图像的局部实例；背景由房间参数派生，未单独复制为设计对象。',[],[EF,'scripts/systems/materialization_system.gd'],'curtain','decor.present','呈现与背景铺设','rule','短房间横向铺底图；高房间保持比例使用一张底图。',['materialized']),
 ('env.door','场景出口','environment','目标房间与目标入口引用组成门交互。',['player','event'],[EF,IS,PS],'arch','door.activate','门交互与切换','interaction','最近可用门在 E 触发后切换房间，移动已有玩家；入口失败有验证。',['candidate','available','transition']),
 ('env.relic','月步遗物','environment','一次性能力拾取，与进度状态分开。',['player','event'],[EF,IS,PS],'moonstep','relic.acquire','能力拾取','interaction','尚未拥有月步才生成，交互后更新能力进度并移除遗物。',['available','collected']),
 ('env.checkpoint','存档神龛','environment','房间中的交互实例；存档/恢复属于共享规则。',['player','event'],[EF,IS,PS],'shrine','checkpoint.activate','祈愿存档','interaction','交互请求治疗、设置检查点并保存。',['available','activated']),
 ('runtime.projectile','纸牌投射物','environment','由攻击生成的短命实体；不能作为永久场景摆件放置。',['time','physics'],[EF,MS,DS,'scripts/systems/effect_system.gd'],'player_card','projectile.travel','飞行 / 命中 / 回收','continuous','按方向和速度移动；碰撞、出界、寿命或房间退出时回收。',['spawned','flying','consumed','removed']),
 ('runtime.hitbox','命中盒','environment','拥有者、阵营、命中去重与寿命构成的无贴图临时对象。',['event','time'],[EF,CS,DS],None,'hitbox.resolve','命中判定','response','生效期与合法拥有者/敌对同房间目标共同决定命中，单次攻击避免重复命中。',['active','expired']),
 ('runtime.effect','程序特效 / 幽灵之手','environment','预警、弧光、冲击、击败、换阶段反馈的临时表现。',['time','event'],[EF,'scripts/systems/effect_system.gd','scripts/systems/materialization_system.gd'],'ghost_hand','effect.expire','表现与寿命','rule','多数效果由程序绘制；ghost_hand 使用贴图。剩余时间结束移除。',['spawned','visible','expired']),
 ('rule.health','伤害与生命规则','rule','阵营、无敌、受伤、死亡与治疗；多角色共同引用。',['event','time'],[DS,'scripts/components/c_health.gd'],None,'health.resolve','生命结果','response','检测阵营/拥有者/房间/无敌，记录伤害与死亡；治疗请求可恢复。',['alive','hurt','dead','heal']),
 ('rule.session','会话 / 暂停 / 地图','session','菜单、游戏、暂停、地图、切换、死亡、结局的顶层状态。',['player','event'],[RT,PS,'scripts/systems/input_system.gd','scripts/components/c_session.gd'],None,'session.mode','会话状态转换','rule','Esc/M 操作会话，非角色动画。非 playing 冻结游戏步长并暂停精灵。',['title','transition','playing','paused','map','dead','ending','error']),
 ('progression.moonstep','探索与能力进度','progression','月步、访问房间和击败首领等跨房间状态。',['event'],[PS,'scripts/components/c_progression.gd'],None,'progression.update','能力 / 探索 / 胜利','rule','能力解锁改变跳跃条件；已获遗物/已败首领不再重复生成。',['unacquired','moonstep','boss_defeated']),
 ('rule.save','存档与重试','rule','神龛和首领胜利触发存档；开新局、门切换、拾取遗物不自动保存。持久化检查点/能力进度，不保存 HP、敌人死亡或首领阶段。',['event'],['scripts/runtime/save_repository.gd','scripts/systems/save_system.gd',RT],None,'save.restore','保存 / 读取 / 恢复','interaction','从检查点恢复，校验存档数据；失败返回状态而非虚构成功。',['none','requested','saved','loaded','error']),
 ('rule.lifecycle','生成 / 放置 / 清理','rule','运行时工厂、队列、唯一位置写入者、房间实体清理。',['event','time'],[RT,EF,MS,'scripts/systems/materialization_system.gd'],None,'lifecycle.materialize','实例生命周期','rule','持久 player 跨房间重定位；临时实例随房间清理；未知类型/缺失资源显式失败。',['queued','materialized','placed','removed']),
 ('ui.game','游戏 UI','interface','HUD、血量/能量、地图、提示、标题/暂停/死亡/结局界面。',['event','player'],['scripts/systems/ui_system.gd','scripts/ui/hud.gd','scripts/main.gd'], 'heart_gem','ui.present','会话与交互反馈','response','根据快照呈现，不生成角色动作；提示仅 playing 且选中可用交互时出现。',['title','hud','notice','pause','map','death','ending']),
 ('rule.camera','跟随镜头','rule','跟随玩家、受房间边界约束。',['event'],['scripts/systems/camera_system.gd','scripts/components/c_camera_target.gd'],None,'camera.follow','跟随与边界','continuous','镜头是视觉规则，与角色运动位置写入分离。',['tracking']),
 ('resource.catalog','共享资源库','resource','图像/图集/帧动画/字体/主题的来源和消费者。',[],[RC,'scripts/systems/materialization_system.gd'],None,'resource.resolve','资源解析与失败','rule','检查绑定、存在性和类型，缺失返回错误。未运行源加载测试。',['registered','resolved','missing','type-mismatch'])]
for id,label,kind,body,drivers,paths,asset,bid,blabel,btype,summary,states in specs:
 obj(id,label,kind,body,drivers,paths,[b(bid,blabel,btype,summary,paths,states)],asset)
# Record visual presentation resources. Copy only first frame of each existing clip, never synthesize a missing clip.
clips=[]
for rid in ['heroine_frames','dealer_frames','boss_frames']:
 p=f'assets/generated/character-bundle/{rid}/{rid}.tres';txt=read(p)
 ext={i:path.removeprefix('res://') for path,i in re.findall(r'path="([^"]+)" id="([^"]+)"',txt)}
 for frames,loop,name,speed in re.findall(r'"frames": \[(.*?)\],\s*"loop": (true|false),\s*"name": &"([^"]+)",\s*"speed": ([\d.]+)',txt,re.S):
  entries=re.findall(r'"duration": ([\d.]+), "texture": ExtResource\("([^"]+)"\)',frames)
  if not entries:raise ValueError('No frames for '+name)
  first=ext[entries[0][1]];dest=out/'assets'/'clips'/f'{rid}-{name}.png';dest.parent.mkdir(exist_ok=True);shutil.copyfile(root/first,dest)
  clips.append(dict(id=rid+'/'+name,name=name,resource=rid,frameCount=len(entries),fps=float(speed),loop=loop=='true',duration=sum(float(d) for d,_ in entries)/float(speed),thumbnail='assets/clips/'+dest.name,preview='first-frame-only',sourceRefs=[ref(p,f'"name": &"{name}"'),ref(p),ref(first) if False else ref(p,'path="res://'+first+'"')]))
clip_ids={c['id'] for c in clips}
for o in objects:
 for behavior in o['behaviors']:
  for c in behavior['presentation']['clips']:
   assert c in clip_ids,c
# Rooms: retain source records in full; no unknown fields discarded.
rooms=[]
for p in [(root/'data/rooms'/(name+'.json')) for name in ['grand_lobby','card_banquet_gallery','roulette_clocktower','quiet_save_room','house_throne']]:
 room=json.loads(p.read_text());rooms.append(room);rp=p.relative_to(root).as_posix();rs=ref(rp)
 groups=[('platforms','env.platform'),('props','env.decor'),('enemies',None),('doors','env.door')]
 for group,did in groups:
  for item in room.get(group,[]):
   target=did or 'actor.enemy.'+item['kind'];iid='instance:'+room['id']+':'+group+':'+item['id']
   instances.append(dict(id=iid,label=item['id'],roomId=room['id'],localId=item['id'],definitionId=target,layer='placed',sourcePath='/'+group+'/'+item['id'],sourceRecord=item,evidence='fact',sourceRefs=[rs],status=status('browser-draft',mapping='record-preserved')))
 for key,target in [('boss','actor.boss'),('relic','env.relic'),('checkpoint','env.checkpoint')]:
  if room.get(key):
   item=room[key];instances.append(dict(id='instance:'+room['id']+':'+key+':'+item['id'],label=item['id'],roomId=room['id'],localId=item['id'],definitionId=target,layer='placed',sourcePath='/'+key,sourceRecord=item,evidence='fact',sourceRefs=[rs],status=status('browser-draft',mapping='record-preserved')))
 for name,pos in room['spawns'].items():
  instances.append(dict(id='marker:'+room['id']+':'+name,label='入口 '+name,roomId=room['id'],localId='spawn:'+name,definitionId='actor.player',layer='spawn-marker',sourcePath='/spawns/'+name,sourceRecord=pos,evidence='fact',sourceRefs=[rs],status=status('browser-draft',mapping='record-preserved')))
for id,target,condition,paths in [('spawn.player','actor.player','运行时初始化创建一次；开局/读取/重试/换房重定位已有玩家。',[EF,RT]),('spawn.enemies.melee','actor.enemy.melee','房间 enemies 中 kind=melee。',[EF]),('spawn.enemies.ranged','actor.enemy.ranged','房间 enemies 中 kind=ranged。',[EF]),('spawn.enemies.flying','actor.enemy.flying','房间 enemies 中 kind=flying。',[EF]),('spawn.boss','actor.boss','room.boss 非空且未击败首领。',[EF]),('spawn.relic','env.relic','room.relic 非空且尚未获得月步。',[EF]),('spawn.projectile','runtime.projectile','施法或首领扇形攻击生成，实例 ID 动态分配。',[CS,EF]),('spawn.hitbox','runtime.hitbox','剑击或首领砸击生效时生成。',[CS,EF]),('spawn.effect','runtime.effect','伤害、预警、攻击事件产生的短命表现。',[CS,DS,BS,EF])]:
 spawn_rules.append(dict(id=id,definitionId=target,condition=condition,runtimeInstances='not-connected',evidence='fact',sourceRefs=[ref(p) for p in paths],status=status()))
# Explicit ownership: coarse file mapping is distinguished from behavior-level evidence.
owners={MS:['actor.player','actor.enemy.melee','actor.enemy.ranged','actor.enemy.flying','actor.boss','runtime.projectile','rule.lifecycle'],CS:['actor.player','actor.enemy.melee','actor.enemy.ranged','actor.enemy.flying','actor.boss'],AS:['actor.player','actor.enemy.melee','actor.enemy.ranged','actor.enemy.flying','actor.boss'],AI:['actor.enemy.melee','actor.enemy.ranged','actor.enemy.flying'],BS:['actor.boss'],DS:['rule.health'],IS:['env.door','env.relic','env.checkpoint','actor.player'],PS:['progression.moonstep','rule.session'],RT:['rule.lifecycle','rule.session'],EF:['rule.lifecycle'],RC:['resource.catalog'],'scripts/systems/camera_system.gd':['rule.camera'],'scripts/systems/effect_system.gd':['runtime.effect','runtime.projectile','runtime.hitbox'],'scripts/systems/input_system.gd':['actor.player','rule.session'],'scripts/systems/materialization_system.gd':['rule.lifecycle','resource.catalog'],'scripts/systems/save_system.gd':['rule.save'],'scripts/runtime/save_repository.gd':['rule.save'],'scripts/runtime/room_catalog.gd':['rule.lifecycle'],'scripts/systems/ui_system.gd':['ui.game'],'scripts/main.gd':['ui.game'],'scripts/entities/game_entity.gd':['rule.lifecycle']}
component_owners={'body':['rule.lifecycle'],'boss':['actor.boss'],'camera_target':['rule.camera'],'checkpoint':['rule.save'],'combat':['actor.player','actor.enemy.melee','actor.enemy.ranged','actor.enemy.flying','actor.boss'],'effect':['runtime.effect'],'enemy_ai':['actor.enemy.melee','actor.enemy.ranged','actor.enemy.flying'],'health':['rule.health'],'hitbox':['runtime.hitbox'],'input':['actor.player','rule.session'],'interaction':['env.door','env.relic','env.checkpoint'],'motion':['actor.player','actor.enemy.melee','actor.enemy.ranged','actor.enemy.flying','actor.boss','runtime.projectile'],'progression':['progression.moonstep'],'projectile':['runtime.projectile'],'room_member':['rule.lifecycle'],'session':['rule.session'],'transform':['rule.lifecycle'],'ui_state':['ui.game'],'visual':['resource.catalog']}
for p in sorted((root/'scripts').rglob('*.gd')):
 rel=p.relative_to(root).as_posix();targets=owners.get(rel)
 if rel.startswith('scripts/ui/'):targets=['ui.game']
 if rel.startswith('scripts/components/'):
  targets=component_owners.get(p.stem.removeprefix('c_'))
  # Only exported declarations, not an arbitrary code parser or complete state-transition proof.
  for n,line in enumerate(read(rel).splitlines(),1):
   match=re.search(r'@export var ([\w]+):.*?= (.*)',line)
   if match:ledger.append(dict(id='field:'+rel+':'+match[1],category='declared-state',disposition='mapped' if targets else 'unmapped',targets=targets or [],reason='组件声明归属；默认值 '+match[2]+'。字段级写回未接入。',granularity='component-ownership',sourceRefs=[ref(rel,line.strip())]))
 ledger.append(dict(id='file:'+rel,category='code',disposition='mapped' if targets else 'unmapped',targets=targets or [],reason='文件职责归属，不声称每条运行路径已验证。',granularity='file-ownership',sourceRefs=[ref(rel)]))
input_map={'move_left':'player.move','move_right':'player.move','jump':'player.jump','sword':'player.sword','card':'player.cast','dodge':'player.dodge','interact':'player.interact','map':'session.mode','pause':'session.mode'}
config=read('project.godot');section=config.split('[input]',1)[1].split('[rendering]',1)[0]
for name in re.findall(r'^(\w+)=\{',section,re.M):
 target=input_map.get(name);ledger.append(dict(id='input:'+name,category='input',disposition='mapped' if target else 'excluded',targets=[target] if target else [],reason='项目动作映射。' if target else 'Godot 内置 ui_* 导航/确认配置；不作为独立角色行为。UI 事件由 ui.game 负责。',granularity='input-action',sourceRefs=[ref('project.godot',name+'={')]))
resource_targets={'heroine_frames':['actor.player'],'dealer_frames':['actor.enemy.melee','actor.enemy.ranged'],'boss_frames':['actor.boss'],'enemy_card':['actor.enemy.flying','actor.enemy.ranged','runtime.projectile'],'player_card':['runtime.projectile'],'ghost_hand':['runtime.effect'],'heart_gem':['ui.game'],'moonstep':['env.relic','ui.game'],'shrine':['env.checkpoint'],'arch':['env.door','env.decor'],'ui_cjk_font':['ui.game']}
for rid,typ,path in re.findall(r'"([^"]+)": \["([^"]+)", "res://([^"]+)"\]',read(RC)):
 assert (root/path).is_file(),path
 targets=resource_targets.get(rid,['env.platform'] if rid.startswith('platform_') else ['env.decor'])
 ledger.append(dict(id='resource:'+rid,category='resource-binding',disposition='mapped',targets=targets,reason=typ+' · '+path,granularity='binding-and-consumers',sourceRefs=[ref(RC,'"'+rid+'":')]))
for clip in clips:
 targets={'heroine_frames':['actor.player'],'dealer_frames':['actor.enemy.melee','actor.enemy.ranged'],'boss_frames':['actor.boss']}[clip['resource']]
 ledger.append(dict(id='clip:'+clip['id'],category='animation-resource',disposition='mapped',targets=targets,sourceRefs=clip['sourceRefs'],reason='存在的帧序列；不代表每个语义状态都有专用动画。',granularity='clip'))
# Explicit state string assignments give a finite source-state denominator without claiming dataflow analysis.
for p,targets in [(CS,owners[CS]),(AI,owners[AI]),(BS,owners[BS]),(PS,owners[PS]),(RT,owners[RT])]:
 for n,line in enumerate(read(p).splitlines(),1):
  if re.search(r'\.(state|mode)\s*=\s*"',line):ledger.append(dict(id='transition:'+p+':'+str(n),category='state-assignment',disposition='mapped',targets=targets,sourceRefs=[ref(p,line.strip())],reason=line.strip(),granularity='system-ownership'))
# UI scenes/theme are a separate source surface, not invisible catalog resources.
for p in sorted((root/'scenes').rglob('*.tscn'))+sorted((root/'resources/ui').glob('*.tres')):
 rel=p.relative_to(root).as_posix();ledger.append(dict(id='presentation:'+rel,category='scene-ui-resource',disposition='mapped',targets=['ui.game'],sourceRefs=[ref(rel)],reason='UI/主题与实际入口配置；不从素材数量推导对象。',granularity='scene-or-theme'))
# Reviewed runtime state strings from source rather than invented universal state enums.
for o in objects:
 for beh in o['behaviors']:
  if beh['id']=='session.mode':beh['limitations']=['状态列表为语义标签；精确字符串见 state-assignment 台账。未在本次运行引擎。']
# Reverse ledger makes every imported semantic fact accountable, including room records and spawning conditions.
for item in objects+[b for o in objects for b in o['behaviors']]+instances+spawn_rules:
 ledger.append(dict(id='semantic:'+item['id'],category='semantic-reverse',disposition='mapped',targets=[item['id']],sourceRefs=item['sourceRefs'],reason='语义项反向证据；不增加独立源发现覆盖率。',granularity='semantic-item'))
for p in [(root/'data/rooms'/(name+'.json')) for name in ['grand_lobby','card_banquet_gallery','roulette_clocktower','quiet_save_room','house_throne']]:
 rid=p.stem;ledger.append(dict(id='room:'+rid,category='scene-data',disposition='mapped',targets=['rule.lifecycle']+[i['id'] for i in instances if i['roomId']==rid],sourceRefs=[ref(p.relative_to(root).as_posix())],reason='完整原始房间记录保留在 sourceRooms；结构字段由规则/实例解释。',granularity='record'))
for p in ['GDD.md','DESIGN.md','ASSETS.md','STRUCTURE.md','SCENES.md']:
 ledger.append(dict(id='design:'+p,category='design-document',disposition='mapped',targets=['resource.catalog' if p in ['ASSETS.md','DESIGN.md'] else 'rule.lifecycle'],sourceRefs=[ref(p)],reason='作为设计意图/结构参考；不将文档愿景当成实现。',granularity='document-reference'))
for category,reason in [('addons/','第三方 ECS/测试插件实现不拆成游戏对象；保留项目使用它们的边界。'),('docs/tags/','历史标签不是当前源快照。'),('.godot/ 与 *.import/*.uid','编辑器缓存和导入标识，不当作游戏语义对象。'),('test/ 与 e2e/','存在的引擎测试不等于本次运行通过；本次只做源/模型/DOM 检查。'),('assets/generated/ 未绑定素材','本次资源分母为 ResourceCatalog 23 个绑定及其中的 SpriteFrames；未枚举所有原始生成候选图片。')]:
 ledger.append(dict(id='exclusion:'+category,category='scope-exclusion',disposition='excluded',targets=[],sourceRefs=[],reason=reason,granularity='scope'))
# Emit source pages only for text evidence; source originals stay untouched.
for path,text in files.items():
 dest=out/'evidence'/(path+'.html');dest.parent.mkdir(parents=True,exist_ok=True)
 rendered=''.join(f'<span class="line" id="L{i}"><a href="#L{i}">{i:4}</a> {html.escape(line)}</span>\n' for i,line in enumerate(text.splitlines(),1))
 dest.write_text('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(path)+'</title><style>body{background:#12111c;color:#ddd;font:14px/1.6 monospace;padding:20px}a{color:#bfa4f6}.line{display:block;min-width:max-content}.line:target{background:#443552}pre{overflow:auto}header{position:sticky;left:0}h1{font:18px sans-serif;overflow-wrap:anywhere}</style><header><a href="javascript:history.back()">返回工作台</a><h1>'+html.escape(path)+'</h1><p>只读源快照 · SHA-256 '+hashlib.sha256((root/path).read_bytes()).hexdigest()+'</p></header><pre>'+rendered+'</pre>')
manifest=[dict(path=path,sha256=hashlib.sha256((root/path).read_bytes()).hexdigest()) for path in sorted(files)]
model=dict(schemaVersion=2,catalogVersion='velvet-semantic-2026-10-07-v2',scope=dict(claim='人工审阅的当前源语义快照；文件/声明状态/输入/资源绑定/房间记录覆盖，不是通用自动解析或完整运行证明。',source='Velvet Eclipse current workspace snapshot',sourceDate='2026-10-07',adapterVersion=1,include=['scripts/**/*.gd','data/rooms/*.json','project.godot input section','ResourceCatalog bindings + SpriteFrames','selected design documents','scenes/**/*.tscn + resources/ui/*.tres'],exclusions=[e['reason'] for e in ledger if e['category']=='scope-exclusion'],verification='static-source + model + DOM; no Godot run in this task'),objects=objects,instances=instances,spawnRules=spawn_rules,clips=clips,sources=sources,ledger=ledger,sourceRooms=rooms,sourceManifest=manifest,migrations=dict(legacyAttackBehavior='player.sword'))
if not lock.exists() or a.accept_reviewed_source:lock.write_text(json.dumps(manifest,indent=2)+'\n')
(out/'semantic-data.json').write_text(json.dumps(model,ensure_ascii=False,indent=2)+'\n');(out/'semantic-data.js').write_text('window.SEMANTIC = '+json.dumps(model,ensure_ascii=False,separators=(',',':'))+';\n')
print(json.dumps({'objects':len(objects),'behaviors':sum(len(o['behaviors']) for o in objects),'instances':len(instances),'spawnRules':len(spawn_rules),'clips':len(clips),'sources':len(sources),'ledger':len(ledger),'sourceFiles':len(manifest),'unmapped':sum(e['disposition']=='unmapped' for e in ledger)}))
