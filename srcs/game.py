#!/usr/bin/env python
#-*- coding:utf-8 -*-
"""
module: player_game
"""
from lib import *
from map.map import Map
from scores import add_score
import math

# 游戏状态
WAITFORPLAYER='waitforplayer'
RUNNING='running'
FINISHED='finished'
MAINTAIN_LEVEL_1 = 1.5
MAINTAIN_LEVEL_2 = 2

#DEFAULT_MAP = 'srcs/map/fight_here.yml'
DEFAULT_MAP = 'srcs/map/test.yml'

MAX_LOST_TURN = 3

TACTIC_COST = {
    'terminator': 3,
    }

class Player():
    def __init__(self, game, name="", side='python'):
        """设置player
        """
        self.game = game
        self.name = name
        self.side = side
        self.id = uuid.uuid4().hex
        self.alive = True

    def get_info(self):
        if self.alive:
            self.status = "alive"
        else:
            self.status = "dead"
        return dict(name=self.name,
                    side=self.side,
                    status=self.status)

class Game():
    """游戏场景"""
    # 记录分数
    def __init__(self,
                 enable_no_resp_die=True,
                 map=None):
        self.enable_no_resp_die = enable_no_resp_die

        if not map:
            m = Map.loadfile(DEFAULT_MAP)
        else:
            m = Map.loadfile(map)
            
        self.set_map(m)            
        
        self.map_max_units = m.max_sum
        self.maintain_fee = m.meta.get('maintain_fee', False)
        self.start()

    def log(self, msg):
        self.logs.append(dict(type='msg', msg=msg))
        # self.logs.append(msg)

    def user_set_map(self, data):
        if self.status != WAITFORPLAYER:
            return "only can set map when the game state is waitforplayer"

        try:
            m = Map.loaddata(data)
            self.set_map(m)
            self.start()
            return 'ok'
        except Exception as e:
            # if error, fall back to default map
            self.set_map(Map.loadfile(DEFAULT_MAP))
            self.start()
            return 'setmap error: ', str(e)
        
    def set_map(self, map):
        self.map = map
        self.planets = self.map.planets
        self.routes = self.map.routes
        self.max_round = self.map.max_round

    def start(self):
        self.logs = []
        self.info = None

        self.round = 0
        self.moves = []
        self.players = []
        self.loop_count = 0
        
        self.player_ops = []
        self.player_points = []
        self.player_tactics = []
        
        self.status = WAITFORPLAYER

        self.holds = [[None, 0] for i in range(len(self.map.planets))]
        
    def add_player(self, name="unknown", side='python'):
        # 限制人数
        if len(self.players) >= self.map.max_player:
            return dict(status="full")
        # 生成玩家
        player = Player(self, name, side)
        self.players.append(player)
        self.player_ops.append(None)
        self.player_points.append(0)
        self.player_tactics.append(None)
        # 强制更新info
        self.info = None
        # 玩家加入地图
        player_id = len(self.players)-1
        planet_id = self.map.starts[player_id]
        self.holds[planet_id] = [player_id, self.map.meta['start_unit']]
        # 用户加入时调整维护费用
        self.adjust_mt_fee()
        # 返回玩家的顺序, 以及玩家的id(用来验证控制权限)
        return dict(seq=len(self.players) - 1, id=player.id)

    def adjust_mt_fee(self):
        """动态调整维修费用"""
        active_players = len([i for i in self.players if i.alive])
        self.mt_base_line = int(self.map_max_units / float(2) / active_players)

    def get_seq(self, id):
        """根据玩家的id获取seq"""
        for i, s in enumerate(self.players):
            if s.id == id:
                return i

    def set_player_op(self, id, kw):
        # 获取玩家的seq
        n = self.get_seq(id)
        if n == None:
            return "noid"
        # 检查玩家是否还活着
        if not self.players[n].alive:
            return "not alive"
        
        try:
            if kw['op'] == 'moves':
                return self.set_player_moves(n, kw)
            else:
                return 'wrong op: ' + kw['op']
        except Exception as e:
            return 'invalid command: ' + e.message

    def set_player_moves(self, n, kw):
        moves = []
        for count, _from, to in kw['moves']:
            count = int(count)
            if count <= 0: continue
            # 检查moves合法性
            owner, armies = self.holds[_from]
            if owner != n:
                self.log('not your planet, round=%s, move=[%s, %s, %s]') % (self.round, armies, _from, to)
                continue
            elif armies < count:
                self.log('not enuough armies, round=%s, move=[%s, %s, %s]') % (self.round, armies, _from, to)
                continue
            elif count < 1:
                self.log('no impositive armies, round=%s, move=[%s, %s, %s]') % (self.round, armies, _from, to)
                continue
            step = self.routes[(_from, to)]
            moves.append([n, _from, to, count, step])
            
        if kw.has_key('tactic'):
            tactic = kw['tactic']
            if tactic['type'] not in TACTIC_COST.keys():
                return "wrong tactic type: %s" % tactic['type']
            if TACTIC_COST[tactic['type']] > self.player_points[n]:
                return "no enough points"
            # todo check tactic
            self.player_tactics[n] = tactic
            
        self.player_ops[n] = moves
        #print 'set_player_op id:%s'% n, self.round, self.player_ops, moves
        return 'ok'

    def do_player_op(self, n):
        for move in self.player_ops[n]:
            # check count <= self.holds[_from]
            side, _from, _to, count, step = move
            if count <= self.holds[_from][1]:
                # go!
                self.holds[_from][1] -= count
                self.moves.append(move)
                self.logs.append(
                    {'type': 'move',
                     'side': side,
                     'from': _from,
                     'to': _to,
                     'count': count,
                     'step': step,
                     })

                # if all my armies gone?
                if self.holds[_from][1] <= 0:
                    self.holds[_from] = [None, 0]
        self.player_ops[n] = None

        if self.player_tactics[n]:
            tactic = self.player_tactics[n]
            if tactic["type"] == 'terminator':
                planet = tactic["planet"]
                self.holds[planet] = [None, 0]
                self.player_points[n] -= TACTIC_COST['terminator']
                self.logs.append({
                    'type': "tactic",
                    'tactic': tactic,
                    })
        self.player_tactics[n] = None
            

    def check_winner(self):
        """
        胜利判断按照: 星球总数, 单位数量, 玩家顺序 依个判断数值哪个玩家最高来算. (不会出现平局)
        同时计算最高分, 保存到历史中
        """
        scores = [
            [p['planets'], p['units'], i]
            for i, p in enumerate(self.get_player_infos())
            ]

        maxid = max(scores)[2]
        winner = self.players[maxid]
        self.log('game finished, winner: ' + winner.name)
        # 再加到最高分里面去
        add_score(datetime.datetime.now(), winner.name)
        return maxid

    def get_map(self):
        return dict(routes=self.map.seq_routes,
                    planets=self.planets,
                    max_round=self.max_round,
                    desc=self.map.desc,
                    name=self.map.name,
                    author=self.map.author,
                    map_size = self.map.map_size,
                    step = GEME_STEP_TIME,
                    )

    def get_player_infos(self):
        player_infos = [p.get_info() for p in self.players]
        # count planets and units
        for p in player_infos:
            p["planets"] = 0
            p["units"] = 0
        for side, count in self.holds:
            if side == None: continue
            player_infos[side]["planets"] += 1
            player_infos[side]["units"] += count
        for move in self.moves:
            side = move[0]
            count = move[3]
            player_infos[side]["units"] += count
        for side, points in enumerate(self.player_points):
            player_infos[side]['points'] = points
        return player_infos

    def get_info(self):
        if self.info:
            return self.info
        
        self.info = dict(round=self.round,
                         status=self.status,
                         players=self.get_player_infos(),
                         moves=self.moves,
                         holds=self.holds,
                         logs=self.logs)
        return self.info

    def check_finished(self):
        """
        检查游戏是否结束
        当回合限制到达或者只有一个玩家剩下的时候, 游戏结束.
        """
        if self.round > self.max_round:
            return True

        player_infos = self.get_player_infos()
        
        # save user alive status
        for i, p in enumerate(player_infos):
            self.players[i].alive = p['units'] > 0

        alives = [True
                  for p in player_infos
                  if p['units'] > 0]
        if sum(alives) <= 1:
            return True

    def move_stage(self):
        for i, d in enumerate(self.player_ops):
            player = self.players[i]
            if not player.alive: continue

            # 如果连续没有响应超过MAX_LOST_TURN次, 让玩家死掉
            if d == None and self.enable_no_resp_die:
                self.no_response_player_die(player, self.round)

            if d != None:
                self.do_player_op(i)

    def arrive_stage(self):
        # time steps
        for move in self.moves:
            move[-1] -= 1
        # find arrived units
        arrives = [move for move in self.moves
                   if move[-1]==0]
        # remove arrived moves
        self.moves = [move for move in self.moves
                      if move[-1]>0]
        return arrives
    
    def battle_stage(self, arrives):
        for i in range(len(self.holds)):
            # move[2] means destination of move
            arrive_moves = [move for move in arrives
	                  if move[2] == i]
            if len(arrive_moves) > 0:
                self.battle_multi(arrive_moves, i)

    def battle_multi(self, arrivemoves, to):
        # 按节点进行结算
        army = {}
        planet_side, planet_count = self.holds[to]
        _def = self.planets[to]['def']
        _old_planet_count = planet_count
        _reinforce_count = 0
        if planet_side != None:
            army[planet_side] = planet_count * _def

	for i,move in enumerate(arrivemoves):
            # move[0] is side of move
            if move[0] not in army:
                army[move[0]] = 0
            army[move[0]] += move[3]

        # 记录援军数量
        if planet_side != None:
            _reinforce_count = army[planet_side] - _old_planet_count * _def

	best_army = None
        for key in army:
            if best_army == None:
                best_army = key
            elif army[key] > army[best_army]:
                best_army = key

        if best_army == None:
            self.logs.append(dict(type = "army",armys = army))
            return
        planet_count = army[best_army]
        if len(army) > 1:
            for key in army:
                # 数量一样的话，全灭
                if key != best_army:
                    if army[key] == army[best_army]:
                        planet_side, planet_count = None, 0
                        break
                    planet_count -= int(math.ceil(army[key]**2/float(army[best_army]*(len(army)-1))))

        if planet_side == None:
            # 如果星球没有驻军, 就占领
            planet_side = best_army
            self.logs.append(dict(type= "occupy",
                                  side=planet_side,
                                  count=planet_count,
                                  planet=to)) 
        else:
            # 防守方加权
            if best_army == planet_side:
                _pre_battle = _old_planet_count * _def + _reinforce_count
                planet_count = int((_reinforce_count + _old_planet_count) *
                                   (planet_count / _pre_battle))
            planet_side = best_army

        self.holds[to] = [planet_side, planet_count]
        

    def mt_level(self, _side, base_line=2000):
        """
        根据 玩家 units & base_line 返回增长系数, 最高为 1
        """
        _units = self.get_info()['players'][_side]['units']
        if _units <= base_line:
            return float(1)
        elif _units <= base_line * MAINTAIN_LEVEL_1:
            return float(0.5)
        elif _units <= base_line * MAINTAIN_LEVEL_2:
            return float(0.25)
        else:
            return float(0)

    def next_round(self):
        # 生产回合
        for i, data in enumerate(self.holds):
            side, count = data
            if side == None: continue
            next = self.count_growth(count, self.planets[i], self.mt_level(side, self.mt_base_line))
            if next <= 0:
                side = None
                next = 0
            self.holds[i] = [side, next]
            self.logs.append(dict(type= "production",
                                  planet=i,
                                  side=side,
                                  count=next))
            
        self.round += 1
        self.player_op = [None, ] * len(self.players)

    def step(self):
        """
        游戏进行一步
        返回值代表游戏是否有更新
        """
        self.logs = []
        self.info = None
        # 如果游戏结束, 等待一会继续开始
        #if self.loop_count <= 10 and self.status in [FINISHED]:
            #self.loop_count += 1
            #return

        if self.status == FINISHED:
            self.loop_count = 0
            self.start()
            return True

        # 游戏开始的时候, 需要有N个以上的玩家加入.
        if self.status == WAITFORPLAYER:
            if len(self.players) < self.map.min_player: return
            self.status = RUNNING
            self.log('game running.')

        # 游戏结束判断
        if self.check_finished():
            self.status = FINISHED
            self.check_winner()
            self.loop_count = 0

        # points
        for i in range(len(self.player_points)):
            self.player_points[i] += 1

        # move stage
        self.move_stage()
        
        # arrive stage
        arrives = self.arrive_stage()
        
        # battle stage
        self.battle_stage(arrives)

        # next round
        self.next_round()
        return True

    def battle(self, move):
        """
        战斗阶段
        首先进行def加权, 星球的单位Xdef 当作星球的战斗力量.
        双方数量一样, 同时全灭, A>B的时候, B全灭, A-B/(A/B) (B/(A/B)按照浮点计算, 最后去掉小数部分到整数)
        如果驻守方胜利, 除回def系数, 去掉小数部分到整数作为剩下的数量.
        """
        side, _from, to, count, _round = move
        planet_side, planet_count = self.holds[to]
        _def = self.planets[to]['def']

        if planet_side == None:
            # 如果星球没有驻军, 就占领
            planet_side = side
            planet_count = count
            self.logs.append(dict(type= "occupy",
                                  side=side,
                                  count=count,
                                  planet=to)) 
        elif side == planet_side:
            # 如果是己方, 就加入
            planet_count += count
            self.logs.append(dict(type= "join",
                                  planet=to,
                                  side=side,
                                  count=count))
        else:
            # 敌方战斗
            # 防守方加权
            planet_count *= _def
            if planet_count == count:
                # 数量一样的话, 同时全灭
                planet_side, planet_count = None, 0
            elif planet_count < count:
                # 进攻方胜利
                planet_side = side
                planet_count = count - int(planet_count**2/float(count))
            else:
                # 防守方胜利                
                planet_count -= int(count**2/float(planet_count))
                planet_count = int(planet_count / _def)
            self.logs.append(dict(type= "battle",
                                  planet=to,
                                  attack=side,
                                  defence=planet_side,
                                  atk_count=count,
                                  def_count=planet_count,
                                  winner=planet_side))
        self.holds[to] = [planet_side, planet_count]

    def count_growth(self, planet_count, planet, mt_proc = 1):
        max = planet['max']
        res = planet['res']
        cos = planet['cos']
        # 兵力增量乘以维护费用水平(增长系数)
        new_armies = (planet_count * (res - 1) + cos)
        if self.maintain_fee: new_armies *= mt_proc
        new_count = int(planet_count + new_armies)
        if planet_count < max:
            planet_count = min(new_count, max)
        elif new_count < planet_count:
            planet_count = new_count
        return planet_count

    def alloped(self):
        """
        判断是否所有玩家都做过操作了
        """
        oped = [
            (not s.alive or op != None)
            for op, s in zip(self.player_op,
                             self.players)]
        return all(oped)

    def no_response_player_die(self, player, round):
        """
        如果连续没有响应超过MAX_LOST_TURN次, 让玩家死掉
        round是没有响应的轮数(用来检查是否连续没有响应)
        
        """
        # 初始化缓存
        if (not hasattr(player, 'no_resp_time') or
            player.no_resp_round != round - 1):
            player.no_resp_time = 1
            player.no_resp_round = round
            return
        # 次数更新
        player.no_resp_time += 1
        player.no_resp_round = round
        # 判断是否没有响应时间过长
        if player.no_resp_time >= MAX_LOST_TURN:
            player.alive = False
            # 用户丢失后调整维护费用
            self.adjust_mt_fee()
            logging.debug('kill no response player: %d' % \
                         self.players.index(player))
            self.log('kill player for no response %s: , round is %s, time is %s' % (player.name, round, player.no_resp_time))


def test():
    """
    # 初始化游戏
    >>> g = Game(enable_no_resp_die=False, map="srcs/map/test.yml")

    # 玩家加入
    >>> player1 = g.add_player('player1')
    >>> player1['seq'] == 0
    True
    >>> player2 = g.add_player('player2')
    >>> player2['seq'] == 1
    True
    >>> g.holds
    [[0, 100], [1, 100], (None, 0), (None, 0), (None, 0)]
    
    # 游戏可以开始了
    >>> g.status == WAITFORPLAYER
    True
    >>> g.round == 0
    True
    >>> g.step()
    True
    >>> g.round == 1
    True
    
    # 一个回合之后, 玩家的单位开始增长了
    >>> g.holds
    [[0, 110], [1, 110], (None, 0), (None, 0), (None, 0)]


    # 玩家开始出兵
    >>> g.set_player_op(player1['id'], {'op': 'moves', 'moves': [[100, 0, 4], ]})
    'ok'
    >>> g.set_player_op(player2['id'], {'op': 'moves', 'moves': [[10, 1, 4], ]})
    'ok'

    # 出兵到达目标星球
    >>> g.step()
    True
    >>> g.moves
    [[0, 0, 4, 100, 1], [1, 1, 4, 10, 1]]

    # 能够获取API
    >>> g.get_map()
    {'planets': [{'res': 1, 'cos': 10, 'pos': (0, 0), 'def': 2, 'max': 1000}, {'res': 1, 'cos': 10, 'pos': (4, 0), 'def': 2, 'max': 1000}, {'res': 1, 'cos': 10, 'pos': (0, 4), 'def': 2, 'max': 1000}, {'res': 1, 'cos': 10, 'pos': (4, 4), 'def': 2, 'max': 1000}, {'res': 1.5, 'cos': 0, 'pos': (2, 2), 'def': 0.5, 'max': 300}], 'name': 'test', 'map_size': (5, 5), 'author': 'halida', 'routes': [(0, 1, 4), (3, 2, 4), (1, 3, 4), (3, 4, 2), (3, 1, 4), (1, 4, 2), (2, 4, 2), (2, 0, 4), (2, 3, 4), (4, 3, 2), (0, 4, 2), (4, 2, 2), (1, 0, 4), (4, 1, 2), (0, 2, 4), (4, 0, 2)], 'max_round': 8000, 'desc': 'this the the standard test map.'}
    >>> g.get_info()
    {'status': 'running', 'players': [{'name': 'player1'}, {'name': 'player2'}], 'moves': [[0, 0, 4, 100, 1], [1, 1, 4, 10, 1]], 'logs': [], 'holds': [[0, 120], [1, 120], (None, 0), (None, 0), (None, 0)], 'round': 2}
    
    # 战斗计算
    >>> g.step()
    True
    >>> g.holds[4]
    [0, 96]

    # 再出一次兵，此时非法操作了
    >>> g.set_player_op(player1['id'], {'op': 'moves', 'moves': [[1000, 0, 4], ]})
    'no enough armies'
    >>> g.set_player_op(player2['id'], {'op': 'moves', 'moves': [[10, 0, 4], ]})
    'not your planet'

    # 结束逻辑测试
    >>> import copy

    # 只有一个玩家剩下的时候, 游戏结束
    >>> gend = copy.deepcopy(g)
    >>> gend.holds[1] = [None, 0]
    >>> gend.step()
    True
    >>> gend.status == FINISHED
    True
    >>> gend.check_winner()
    0
    
    # 回合数到的时候, 星球多的玩家胜利
    >>> gend = copy.deepcopy(g)
    >>> gend.round = 10000
    >>> gend.step()
    True
    >>> gend.status == FINISHED
    True
    >>> gend.check_winner()
    0
    
    # 回合数到的时候, 星球一样, 单位多的玩家胜利
    >>> gend = copy.deepcopy(g)
    >>> gend.round = 10000
    >>> gend.holds[4] = [None, 0]
    >>> gend.step()
    True
    >>> gend.status == FINISHED
    True
    >>> gend.check_winner()
    1
    
    # 回合数到的时候, 星球一样, 单位一样, 序号后面的玩家胜利
    >>> gend = copy.deepcopy(g)
    >>> gend.round = 10000
    >>> gend.holds[4] = [None, 0]
    >>> gend.holds[0] = [0, 100]
    >>> gend.holds[1] = [1, 100]
    >>> gend.step()
    True
    >>> gend.status == FINISHED
    True
    >>> gend.check_winner()
    1
    """
    import doctest
    doctest.testmod()
    
if __name__=="__main__":
    test()
