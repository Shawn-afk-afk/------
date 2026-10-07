"""
ExamCrafter AI - 外掛式圖表繪製引擎 (Pluggable Chart Engine)
功能：使用 Python (Matplotlib/Pillow) 動態生成 300 DPI 高對比黑白/灰階印刷圖表。
支援科目：地理、歷史、公民、英文、國文等。
支援透過 @ChartRegistry.register("chart_name") 隨時擴充新圖表類型。
"""

import os
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as patches

# 顯式指定系統繁體中文字體與支援負號
plt.rcParams['font.sans-serif'] = ['Microsoft JhengHei', 'DFKai-SB', 'PingFang TC', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False


class ChartRegistry:
    """外掛註冊者中心"""
    _plugins = {}

    @classmethod
    def register(cls, chart_type):
        """外掛註冊裝飾器"""
        def decorator(fn):
            cls._plugins[chart_type] = fn
            return fn
        return decorator

    @classmethod
    def generate(cls, chart_type, params, output_path):
        """根據 chart_type 調用對應繪圖插件"""
        if chart_type in cls._plugins:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            return cls._plugins[chart_type](params, output_path)
        raise ValueError(f"未知的圖表類型: '{chart_type}'. 可用插件: {list(cls._plugins.keys())}")

    @classmethod
    def list_available_charts(cls):
        return list(cls._plugins.keys())


# ==========================================
# 1. 地理科外掛：區域填圖與代號標註 (geo_map_labeling)
# ==========================================
@ChartRegistry.register("geo_map_labeling")
def draw_geo_map_labeling(params, output_path):
    """
    參數範例:
    params = {
        "title": "圖(一) 東北亞與周邊海域示意圖",
        "labels": {"甲": (0.3, 0.7), "乙": (0.7, 0.6), "丙": (0.5, 0.2), "丁": (0.8, 0.2)}
    }
    """
    title = params.get("title", "區域地理示意圖")
    labels = params.get("labels", {"甲": (0.3, 0.7), "乙": (0.7, 0.6), "丙": (0.4, 0.3), "丁": (0.8, 0.2)})

    fig, ax = plt.subplots(figsize=(5.5, 3.8), dpi=300)
    ax.set_facecolor('#f8f9fa')

    # 繪製黑白高對比簡化陸地板塊示意
    rect1 = patches.Rectangle((0.15, 0.45), 0.35, 0.45, linewidth=1.5, edgecolor='black', facecolor='#e9ecef')
    rect2 = patches.Polygon([[0.6, 0.4], [0.85, 0.75], [0.75, 0.3]], closed=True, linewidth=1.5, edgecolor='black', facecolor='#dee2e6')
    ax.add_patch(rect1)
    ax.add_patch(rect2)

    # 繪製代號標籤 (甲、乙、丙、丁)
    for lbl, (x, y) in labels.items():
        ax.plot(x, y, marker='o', color='black', markersize=6)
        ax.text(x + 0.03, y + 0.03, lbl, fontsize=12, fontweight='bold', color='black',
                bbox=dict(boxstyle='square,pad=0.2', facecolor='white', edgecolor='black', linewidth=1))

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(title, fontsize=10.5, fontweight='bold', pad=10)

    # 加上比例尺與指北針示意
    ax.annotate('N', xy=(0.08, 0.9), xytext=(0.08, 0.78),
                arrowprops=dict(facecolor='black', width=1.5, headwidth=6),
                ha='center', va='center', fontsize=9, fontweight='bold')

    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()
    return output_path


# ==========================================
# 2. 地理科外掛：氣候月均溫與雨量圖 (climate_data_table)
# ==========================================
@ChartRegistry.register("climate_data_table")
def draw_climate_chart(params, output_path):
    """
    參數範例:
    params = {
        "city_name": "東京 (Tokyo)",
        "temperatures": [5.2, 5.7, 8.7, 13.9, 18.2, 21.4, 25.0, 26.4, 22.8, 17.5, 12.1, 7.6],
        "rainfall": [52, 56, 117, 124, 137, 167, 153, 168, 209, 197, 92, 51]
    }
    """
    city = params.get("city_name", "城市氣候圖")
    months = [str(i) for i in range(1, 13)]
    temps = params.get("temperatures", [5, 6, 9, 14, 18, 21, 25, 26, 23, 17, 12, 7])
    rain = params.get("rainfall", [50, 60, 110, 120, 140, 170, 150, 160, 200, 190, 90, 50])

    fig, ax1 = plt.subplots(figsize=(5.5, 3.5), dpi=300)

    # 降水量柱狀圖 (黑白灰階風格)
    ax1.bar(months, rain, color='#adb5bd', edgecolor='black', linewidth=0.8, width=0.6, label='降水量 (mm)')
    ax1.set_ylabel('降水量 (mm)', fontsize=9)
    ax1.set_ylim(0, max(rain) * 1.3)
    ax1.set_xlabel('月份', fontsize=9)

    # 氣溫折線圖
    ax2 = ax1.twinx()
    ax2.plot(months, temps, color='black', marker='o', linewidth=1.5, markersize=4, label='氣溫 (°C)')
    ax2.set_ylabel('氣溫 (°C)', fontsize=9)
    ax2.set_ylim(-10, 35)

    plt.title(f"{city} 氣候圖", fontsize=10.5, fontweight='bold')
    fig.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()
    return output_path


# ==========================================
# 3. 歷史科外掛：歷史事件時間軸 (history_timeline)
# ==========================================
@ChartRegistry.register("history_timeline")
def draw_history_timeline(params, output_path):
    """
    參數範例:
    params = {
        "title": "晚清自強運動與外患大事年表",
        "events": [
            ("1842", "南京條約"),
            ("1860", "自強運動開始"),
            ("1895", "馬關條約"),
            ("1898", "戊戌變法"),
            ("1901", "辛丑條約")
        ]
    }
    """
    title = params.get("title", "歷史年代大事時間軸")
    events = params.get("events", [("1842", "事件甲"), ("1860", "事件乙"), ("1895", "事件丙"), ("1900", "事件丁")])

    fig, ax = plt.subplots(figsize=(6.0, 2.5), dpi=300)
    ax.axhline(0.5, color='black', linewidth=1.5)

    n = len(events)
    xs = [0.1 + i * (0.8 / max(1, n - 1)) for i in range(n)]

    for idx, (year, ev) in enumerate(events):
        x = xs[idx]
        ax.plot(x, 0.5, marker='o', markersize=6, color='black')
        # 年代在下方，事件名稱在上方
        ax.text(x, 0.35, year, ha='center', va='top', fontsize=9, fontweight='bold')
        ax.text(x, 0.65, ev, ha='center', va='bottom', fontsize=9, rotation=25,
                bbox=dict(boxstyle='round,pad=0.2', facecolor='white', edgecolor='black', linewidth=0.8))

    ax.set_xlim(0, 1)
    ax.set_ylim(0.1, 1.0)
    ax.axis('off')
    ax.set_title(title, fontsize=10.5, fontweight='bold', pad=15)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()
    return output_path


# ==========================================
# 4. 公民科外掛：政府組織架構圖 (gov_org_chart)
# ==========================================
@ChartRegistry.register("gov_org_chart")
def draw_gov_org_chart(params, output_path):
    """
    參數範例:
    params = {
        "title": "我國中央五院組織分工示意圖",
        "root": "中華民國政府",
        "branches": ["行政院", "立法院", "司法院", "考試院", "監察院"]
    }
    """
    title = params.get("title", "組織架構圖")
    branches = params.get("branches", ["行政院", "立法院", "司法院", "考試院", "監察院"])
    root = params.get("root", "中央政府")

    fig, ax = plt.subplots(figsize=(6.0, 3.0), dpi=300)

    # 頂部根節點
    ax.text(0.5, 0.8, root, ha='center', va='center', fontsize=10.5, fontweight='bold',
            bbox=dict(boxstyle='square,pad=0.4', facecolor='#e9ecef', edgecolor='black', linewidth=1.2))

    # 子節點
    n = len(branches)
    xs = [0.1 + i * (0.8 / max(1, n - 1)) for i in range(n)]

    for x, b in zip(xs, branches):
        ax.plot([0.5, x], [0.72, 0.4], color='black', linewidth=1.0)
        ax.text(x, 0.3, b, ha='center', va='center', fontsize=9,
                bbox=dict(boxstyle='square,pad=0.3', facecolor='white', edgecolor='black', linewidth=0.8))

    ax.set_xlim(0, 1)
    ax.set_ylim(0.1, 0.95)
    ax.axis('off')
    ax.set_title(title, fontsize=10.5, fontweight='bold')

    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()
    return output_path


# ==========================================
# 5. 英文科外掛：超商內部平面動線圖 (supermarket_layout)
# ==========================================
@ChartRegistry.register("supermarket_layout")
def draw_supermarket_layout(params, output_path):
    """
    參數範例:
    params = {
        "title": "Supermarket Floor Plan",
        "zones": [
            ("Entrance", 0.8, 0.15),
            ("Checkout", 0.6, 0.15),
            ("Fresh Produce", 0.2, 0.2),
            ("Snacks & Candies", 0.5, 0.5),
            ("Daily Milk / Dairy", 0.2, 0.8)
        ]
    }
    """
    title = params.get("title", "Supermarket Floor Plan")

    fig, ax = plt.subplots(figsize=(5.5, 3.5), dpi=300)
    ax.set_facecolor('#ffffff')

    # 外牆
    wall = patches.Rectangle((0.05, 0.05), 0.9, 0.9, linewidth=2, edgecolor='black', facecolor='none')
    ax.add_patch(wall)

    # 入口與收銀
    ax.text(0.8, 0.12, "Entrance ->", ha='center', fontsize=8.5, fontweight='bold')
    ax.text(0.55, 0.12, "[Checkout]", ha='center', fontsize=8.5,
            bbox=dict(boxstyle='square,pad=0.2', facecolor='#e9ecef', edgecolor='black'))

    # 各貨架區
    ax.text(0.2, 0.25, "Fresh Vegetables\n& Fruits", ha='center', fontsize=8,
            bbox=dict(boxstyle='square,pad=0.3', facecolor='#dee2e6', edgecolor='black'))
    ax.text(0.5, 0.55, "Discount Snacks\n(Eye Level)", ha='center', fontsize=8,
            bbox=dict(boxstyle='square,pad=0.3', facecolor='#dee2e6', edgecolor='black'))
    ax.text(0.25, 0.82, "Milk & Dairy\n(Back Wall)", ha='center', fontsize=8,
            bbox=dict(boxstyle='square,pad=0.3', facecolor='#ced4da', edgecolor='black'))

    # 行走動線虛線
    ax.annotate('', xy=(0.25, 0.72), xytext=(0.75, 0.2),
                arrowprops=dict(facecolor='black', width=1, headwidth=5, linestyle='--'))

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    ax.set_title(title, fontsize=10, fontweight='bold', pad=8)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()
    return output_path


# ==========================================
# 6. 英文科外掛：SDGs 減塑長條圖 (sdg_bar_chart)
# ==========================================
@ChartRegistry.register("sdg_bar_chart")
def draw_sdg_bar_chart(params, output_path):
    """
    參數範例:
    params = {
        "title": "Weekly Plastic Bags Used per Student",
        "categories": ["Week 1\n(Before)", "Week 2\n(Action)", "Week 3\n(Habit)"],
        "values": [14, 5, 2]
    }
    """
    title = params.get("title", "Plastic Bag Usage (SDG 12)")
    cats = params.get("categories", ["Week 1", "Week 2", "Week 3"])
    vals = params.get("values", [14, 5, 2])

    fig, ax = plt.subplots(figsize=(4.8, 3.0), dpi=300)
    bars = ax.bar(cats, vals, color=['#495057', '#adb5bd', '#dee2e6'], edgecolor='black', linewidth=1, width=0.5)

    for b in bars:
        height = b.get_height()
        ax.annotate(f'{height}',
                    xy=(b.get_x() + b.get_width() / 2, height),
                    xytext=(0, 3), textcoords="offset points",
                    ha='center', va='bottom', fontsize=9, fontweight='bold')

    ax.set_ylabel("Quantity (bags)", fontsize=8.5)
    ax.set_ylim(0, max(vals) * 1.25)
    ax.set_title(title, fontsize=9.5, fontweight='bold')

    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()
    return output_path


# ==========================================
# 7. 英文會考核心外掛 A (70%)：生活告示、海報、營業時間與價目表 (notice_poster)
# ==========================================
@ChartRegistry.register("notice_poster")
def draw_notice_poster(params, output_path):
    """
    生活告示牌/活動海報 (Notice / Store Poster / Menu / Opening Hours)
    高解析黑白線條排版，適合國中會考生活化題型
    """
    title = params.get("title", "SUNSHINE BAKERY - SPECIAL NOTICE")
    subtitle = params.get("subtitle", "Weekend Sale & New Business Hours")
    hours = params.get("hours", "Monday - Friday: 08:00 - 20:00\nSaturday - Sunday: 09:00 - 18:00")
    items = params.get("items", [
        "1. Buy 2 loafs of bread, get 1 free milk tea!",
        "2. Student discount: 10% off with school ID card.",
        "3. Afternoon tea combo: Coffee + Cake for only $60."
    ])
    notes = params.get("notes", "* Cash, credit cards, and EasyCard accepted. No pets inside.")

    fig, ax = plt.subplots(figsize=(5.2, 3.8), dpi=300)
    ax.set_facecolor('#ffffff')

    # 外框與標題裝飾線 (雙層框線)
    outer_box = patches.FancyBboxPatch((0.04, 0.04), 0.92, 0.92,
                                       boxstyle="round,pad=0.02,rounding_size=0.03",
                                       linewidth=2, edgecolor='black', facecolor='none')
    inner_box = patches.FancyBboxPatch((0.06, 0.06), 0.88, 0.88,
                                       boxstyle="round,pad=0.02,rounding_size=0.02",
                                       linewidth=0.8, edgecolor='#666666', facecolor='#fafafa')
    ax.add_patch(outer_box)
    ax.add_patch(inner_box)

    # 主標題 (粗體橫幅)
    ax.text(0.5, 0.86, title, ha='center', va='center', fontsize=10.5, fontweight='bold', color='black',
            bbox=dict(boxstyle='square,pad=0.3', facecolor='#e2e8f0', edgecolor='black', linewidth=1))

    # 副標題
    ax.text(0.5, 0.77, subtitle, ha='center', va='center', fontsize=8.5, style='italic', color='#333333')

    # 營業時間區塊
    ax.plot([0.1, 0.9], [0.71, 0.71], color='black', linewidth=0.8, linestyle='--')
    ax.text(0.12, 0.63, "【Opening Hours】\n" + hours, ha='left', va='center', fontsize=8, color='#111111')

    # 活動優惠區塊
    ax.plot([0.1, 0.9], [0.52, 0.52], color='black', linewidth=0.8, linestyle='--')
    items_text = "【Special Deals & Offers】\n" + "\n".join(items)
    ax.text(0.12, 0.35, items_text, ha='left', va='center', fontsize=8, color='#111111')

    # 底部注意事項
    ax.plot([0.1, 0.9], [0.18, 0.18], color='black', linewidth=0.8)
    ax.text(0.5, 0.12, notes, ha='center', va='center', fontsize=7.5, color='#444444')

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')

    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()
    return output_path


# ==========================================
# 8. 英文會考核心外掛 B (20%)：空間方位與城鎮地圖 (street_map)
# ==========================================
@ChartRegistry.register("street_map")
def draw_street_map(params, output_path):
    """
    城鎮地圖與空間方位問路圖 (Town Street Map)
    包含街道名稱、各建築位置與 "You Are Here" 起點
    """
    title = params.get("title", "Map of Green Town")
    buildings = params.get("buildings", [
        ("Post Office", 0.15, 0.75, 0.25, 0.16),
        ("Hospital", 0.6, 0.75, 0.25, 0.16),
        ("Park", 0.15, 0.15, 0.25, 0.22),
        ("Supermarket", 0.6, 0.22, 0.25, 0.15),
        ("Library", 0.6, 0.44, 0.25, 0.14)
    ])

    fig, ax = plt.subplots(figsize=(5.2, 3.8), dpi=300)
    ax.set_facecolor('#ffffff')

    # 外邊框
    frame = patches.Rectangle((0.02, 0.02), 0.96, 0.96, linewidth=1.5, edgecolor='black', facecolor='none')
    ax.add_patch(frame)

    # 街道 (灰色十字馬路)
    # 東西向 Main Street
    ax.add_patch(patches.Rectangle((0.02, 0.58), 0.96, 0.14, facecolor='#f1f5f9', edgecolor='black', linewidth=0.8))
    ax.plot([0.02, 0.98], [0.65, 0.65], color='#94a3b8', linestyle='--', linewidth=1)
    ax.text(0.5, 0.65, "--- Main Street ---", ha='center', va='center', fontsize=8.5, fontweight='bold', color='#475569')

    # 南北向 Park Road
    ax.add_patch(patches.Rectangle((0.42, 0.02), 0.15, 0.96, facecolor='#f1f5f9', edgecolor='black', linewidth=0.8))
    ax.plot([0.495, 0.495], [0.02, 0.98], color='#94a3b8', linestyle='--', linewidth=1)
    ax.text(0.495, 0.91, "Park\nRoad", ha='center', va='center', fontsize=8, fontweight='bold', color='#475569')

    # 繪製各個建築物方塊
    for name, bx, by, bw, bh in buildings:
        b_patch = patches.FancyBboxPatch((bx, by), bw, bh,
                                         boxstyle="square,pad=0.01",
                                         linewidth=1.2, edgecolor='black', facecolor='#e2e8f0')
        ax.add_patch(b_patch)
        ax.text(bx + bw / 2, by + bh / 2, name, ha='center', va='center', fontsize=8.5, fontweight='bold')

    # 起點 "YOU ARE HERE" 標記
    ax.plot(0.27, 0.61, marker='*', color='black', markersize=12)
    ax.text(0.27, 0.54, "YOU ARE HERE", ha='center', va='top', fontsize=7.5, fontweight='bold',
            bbox=dict(boxstyle='square,pad=0.15', facecolor='#fef08a', edgecolor='black', linewidth=0.8))

    # 指北針 (Compass)
    ax.add_patch(patches.Circle((0.9, 0.88), 0.06, facecolor='white', edgecolor='black', linewidth=1))
    ax.annotate('N', xy=(0.9, 0.92), xytext=(0.9, 0.85),
                arrowprops=dict(facecolor='black', width=1.5, headwidth=5),
                ha='center', va='center', fontsize=8, fontweight='bold')

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    ax.set_title(title, fontsize=10, fontweight='bold', pad=8)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()
    return output_path


# ==========================================
# 9. 英文會考核心外掛 C (10%)：生活問卷調查長條圖 (survey_bar_chart)
# ==========================================
@ChartRegistry.register("survey_bar_chart")
def draw_survey_bar_chart(params, output_path):
    """
    學生調查問卷長條圖 (Student Survey Bar Chart)
    """
    title = params.get("title", "Survey: 100 Students' Favorite Weekend Activities")
    categories = params.get("categories", ["Playing\nSports", "Reading\nBooks", "Watching\nMovies", "Playing\nVideo Games"])
    values = params.get("values", [38, 26, 21, 15])

    fig, ax = plt.subplots(figsize=(5.0, 3.2), dpi=300)
    ax.set_facecolor('#ffffff')

    bars = ax.bar(categories, values, color=['#334155', '#64748b', '#94a3b8', '#cbd5e1'],
                  edgecolor='black', linewidth=1, width=0.55)

    for b in bars:
        h = b.get_height()
        ax.annotate(f"{h}%",
                    xy=(b.get_x() + b.get_width() / 2, h),
                    xytext=(0, 4), textcoords="offset points",
                    ha='center', va='bottom', fontsize=8.5, fontweight='bold')

    ax.set_ylabel("Number of Students (%)", fontsize=8.5)
    ax.set_ylim(0, max(values) * 1.25)
    ax.set_title(title, fontsize=9.5, fontweight='bold', pad=8)

    # 刻度樣式
    ax.tick_params(axis='x', labelsize=8)
    ax.tick_params(axis='y', labelsize=8)
    ax.grid(axis='y', linestyle=':', alpha=0.6)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300)
    plt.close()
    return output_path


# ==========================================
# 英文科專屬圖表隨機分配與統一調度函式
# ==========================================
def generate_english_exam_chart(q_num: int, chart_type: str = None, spec: dict = None, output_dir: str = "output_exams/charts"):
    """
    依比例自動隨機輪換國中會考三大標準圖片題樣式：
    70% notice_poster (生活海報告示)
    20% street_map (方位地圖)
    10% survey_bar_chart (問卷調查長條圖)
    """
    import random
    os.makedirs(output_dir, exist_ok=True)

    if not chart_type:
        rand_val = random.random()
        if rand_val < 0.70:
            chart_type = "notice_poster"
        elif rand_val < 0.90:
            chart_type = "street_map"
        else:
            chart_type = "survey_bar_chart"

    filename = f"q_{q_num}_{chart_type}_{random.randint(1000, 9999)}.png"
    output_path = os.path.join(output_dir, filename)

    if not spec:
        spec = {}

    ChartRegistry.generate(chart_type, spec, output_path)
    return output_path, chart_type, spec

