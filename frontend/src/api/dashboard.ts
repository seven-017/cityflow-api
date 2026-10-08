import { get } from '@/api/http'
import type { DashboardOverview } from '@/types/dashboard'

/**
 * 首页那一整页的聚合。
 *
 * 这个接口没有参数 —— 它答的是「现在怎么样」，不是「某段时间怎么样」
 * （带日期条件那个是另一个接口）。
 *
 * 耗时是两段的：**冷启动要十几秒**（实测 14.7 秒，五个聚合挨个跑），
 * 之后五分钟内再来是毫秒级（0.27 秒，走的是后端进程内的缓存，压根不碰数据库）。
 *
 * 所以调用方得做好「第一次进来要等一会儿」的准备，
 * 别写一个十秒的 timeout 把它误杀了 —— http.ts 里那个 60 秒就是给它留的
 */
export function getDashboardOverview(): Promise<DashboardOverview> {
  return get<DashboardOverview>('/dashboard/overview')
}
