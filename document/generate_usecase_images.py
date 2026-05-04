"""Generate use-case visualization images for the Kinetica Graph User Guide."""
import os, json, subprocess, sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx
import numpy as np

os.chdir('/home/kkaramete/graph')
sys.path.insert(0, '/home/kkaramete/graph')
IMG_DIR = '/home/kkaramete/graph/images'
os.makedirs(IMG_DIR, exist_ok=True)

CLI = "/home/kkaramete/.claude/plugins/cache/kinetica-skills/kineticadb/1.0.27/skills/kinetica-execute/scripts/kinetica-cli.py"

def run_query(sql, timeout=60000):
    env = {**os.environ, 'KINETICA_DB_SKILL_TIMEOUT': str(timeout)}
    r = subprocess.run(['python3', CLI, 'query', sql], capture_output=True, text=True, env=env)
    if r.returncode != 0:
        print(f"Query error: {r.stderr[:200]}")
        return None
    return json.loads(r.stdout)

# ─────────────────────────────────────────────────────────────
# 1. BANKING GRAPH — Risk network visualization
# ─────────────────────────────────────────────────────────────
print("Generating banking graph image...")
banking_data = run_query("""
    GRAPH expero.banking_graph
    MATCH (a:bank)-[ab:performed]->(b:wire_message WHERE b.wire_message_risk_score > 50)
          -[bc:is_for_transaction]->(c:banking_transaction)
    RETURN a.bank_name AS bank, b.NODE AS wire, b.wire_message_risk_score AS risk,
           c.banking_transaction_amount AS amount
""")

if banking_data and banking_data.get('records'):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 7))
    fig.patch.set_facecolor('#0d1117')

    records = banking_data['records']

    # Left: Network graph
    G = nx.DiGraph()
    banks = set()
    wires = set()
    for r in records[:40]:
        bank = r.get('bank', 'Unknown')[:20]
        wire = r.get('wire', '')[:8]
        banks.add(bank)
        wires.add(wire)
        G.add_edge(bank, wire)

    if G.number_of_nodes() > 0:
        pos = nx.spring_layout(G, k=2, seed=42)
        bank_nodes = [n for n in G.nodes() if n in banks]
        wire_nodes = [n for n in G.nodes() if n in wires]

        nx.draw_networkx_nodes(G, pos, nodelist=bank_nodes, node_color='#58a6ff',
                              node_size=800, alpha=0.9, ax=ax1)
        nx.draw_networkx_nodes(G, pos, nodelist=wire_nodes, node_color='#f85149',
                              node_size=200, alpha=0.6, ax=ax1)
        nx.draw_networkx_edges(G, pos, edge_color='#8b949e', alpha=0.4,
                              arrows=True, arrowsize=10, ax=ax1)
        nx.draw_networkx_labels(G, pos, {n: n for n in bank_nodes},
                               font_size=7, font_color='white', ax=ax1)

    ax1.set_facecolor('#0d1117')
    ax1.set_title('Bank → Wire Transfer Network (risk > 50)', color='white', fontsize=12, pad=10)
    legend1 = [mpatches.Patch(color='#58a6ff', label='Banks'),
               mpatches.Patch(color='#f85149', label='Wire Messages')]
    ax1.legend(handles=legend1, loc='upper left', facecolor='#161b22',
              edgecolor='#30363d', labelcolor='white', fontsize=9)

    # Right: Risk distribution
    risks = [float(r.get('risk', 0)) for r in records if r.get('risk')]
    amounts = [float(r.get('amount', 0)) for r in records if r.get('amount')]

    if risks and amounts:
        scatter = ax2.scatter(risks, amounts, c=risks, cmap='RdYlGn_r',
                            s=40, alpha=0.7, edgecolors='#30363d', linewidth=0.5)
        ax2.set_xlabel('Wire Message Risk Score', color='#8b949e', fontsize=10)
        ax2.set_ylabel('Transaction Amount ($)', color='#8b949e', fontsize=10)
        ax2.set_title('Risk vs Transaction Amount', color='white', fontsize=12, pad=10)
        ax2.set_facecolor('#0d1117')
        ax2.tick_params(colors='#8b949e')
        for spine in ax2.spines.values():
            spine.set_color('#30363d')
        plt.colorbar(scatter, ax=ax2, label='Risk Score')

    plt.tight_layout()
    plt.savefig(f'{IMG_DIR}/usecase_banking.png', dpi=150, bbox_inches='tight',
                facecolor='#0d1117', edgecolor='none')
    plt.close()
    print("  -> usecase_banking.png")
else:
    print("  -> Banking query returned no data, skipping")

# ─────────────────────────────────────────────────────────────
# 2. BLUESKY SOCIAL NETWORK — User-post interactions
# ─────────────────────────────────────────────────────────────
print("Generating social network image...")
social_data = run_query("""
    GRAPH bluesky
    MATCH (a)-[e]->(b)
    RETURN a.node AS source, a.label AS src_label, e.LABEL AS edge_type,
           b.node AS target, b.label AS tgt_label
""")

if social_data and social_data.get('records'):
    fig, ax = plt.subplots(figsize=(12, 8))
    fig.patch.set_facecolor('#0d1117')

    G = nx.DiGraph()
    node_types = {}
    edge_colors_map = {'posted': '#7c3aed', 'liked': '#f97316', 'follows': '#22c55e'}

    for r in social_data['records']:
        src, tgt, etype = r['source'], r['target'], r.get('edge_type', '')
        G.add_edge(src, tgt, label=etype)
        # Determine type from label
        src_lbl = r.get('src_label', '')
        tgt_lbl = r.get('tgt_label', '')
        if 'user' in str(src_lbl).lower():
            node_types[src] = 'user'
        elif 'post' in str(src_lbl).lower():
            node_types[src] = 'post'
        if 'user' in str(tgt_lbl).lower():
            node_types[tgt] = 'user'
        elif 'post' in str(tgt_lbl).lower():
            node_types[tgt] = 'post'

    pos = nx.spring_layout(G, k=3, seed=42)
    users = [n for n in G.nodes() if node_types.get(n) == 'user']
    posts = [n for n in G.nodes() if node_types.get(n) == 'post']

    nx.draw_networkx_nodes(G, pos, nodelist=users, node_color='#58a6ff',
                          node_size=1200, alpha=0.9, ax=ax, node_shape='o')
    nx.draw_networkx_nodes(G, pos, nodelist=posts, node_color='#f97316',
                          node_size=800, alpha=0.8, ax=ax, node_shape='s')

    for u, v, d in G.edges(data=True):
        color = edge_colors_map.get(d.get('label', ''), '#8b949e')
        nx.draw_networkx_edges(G, pos, edgelist=[(u, v)], edge_color=color,
                              arrows=True, arrowsize=20, width=2, alpha=0.7,
                              connectionstyle='arc3,rad=0.1', ax=ax)

    nx.draw_networkx_labels(G, pos, font_size=11, font_color='white',
                           font_weight='bold', ax=ax)

    # Edge labels
    edge_labels = {(u, v): d.get('label', '') for u, v, d in G.edges(data=True)}
    nx.draw_networkx_edge_labels(G, pos, edge_labels, font_size=8,
                                 font_color='#8b949e', ax=ax)

    ax.set_facecolor('#0d1117')
    ax.set_title('Bluesky Social Network — Users & Posts', color='white', fontsize=14, pad=15)
    legend = [mpatches.Patch(color='#58a6ff', label='Users'),
              mpatches.Patch(color='#f97316', label='Posts'),
              mpatches.Patch(color='#7c3aed', label='posted'),
              mpatches.Patch(color='#f97316', label='liked')]
    ax.legend(handles=legend, loc='upper left', facecolor='#161b22',
             edgecolor='#30363d', labelcolor='white', fontsize=10)

    plt.tight_layout()
    plt.savefig(f'{IMG_DIR}/usecase_social.png', dpi=150, bbox_inches='tight',
                facecolor='#0d1117', edgecolor='none')
    plt.close()
    print("  -> usecase_social.png")
else:
    print("  -> Social query returned no data, skipping")

# ─────────────────────────────────────────────────────────────
# 3. LOGISTICS — Multi-modal transport network (rearm graph)
# ─────────────────────────────────────────────────────────────
print("Generating logistics image...")
logistics_data = run_query("""
    GRAPH rearm
    MATCH (a)-[e]->(b)
    RETURN a.node AS src, a.label AS src_label, e.LABEL AS edge_type,
           e.weight AS weight, b.node AS tgt, b.label AS tgt_label
""")

if not logistics_data or not logistics_data.get('records'):
    # Rearm might not exist, try creating from the known test data
    print("  -> Rearm graph not available, generating from static data")
    logistics_data = None

if logistics_data and logistics_data.get('records'):
    fig, ax = plt.subplots(figsize=(12, 8))
    fig.patch.set_facecolor('#0d1117')

    G = nx.DiGraph()
    node_labels_map = {}
    transport_colors = {'AIR': '#ef4444', 'SEA': '#3b82f6', 'LAND': '#22c55e'}

    for r in logistics_data['records']:
        src, tgt = str(r['src']), str(r['tgt'])
        etype = r.get('edge_type', '')
        w = r.get('weight', '')
        G.add_edge(src, tgt, label=etype, weight=float(w) if w else 1)
        node_labels_map[src] = str(r.get('src_label', ''))
        node_labels_map[tgt] = str(r.get('tgt_label', ''))

    # Position nodes in a logical layout (hub-and-spoke)
    # Assign positions based on node type
    hub_colors = {'MAINHUB': '#ef4444', 'USHUB': '#f97316', 'SEAHUB': '#3b82f6',
                  'LANDHUB': '#22c55e', 'SPOKE': '#a78bfa'}

    pos = nx.spring_layout(G, k=3, seed=42)
    for node in G.nodes():
        label = node_labels_map.get(node, '')
        color = '#8b949e'
        for key, c in hub_colors.items():
            if key in label.upper():
                color = c
                break
        nx.draw_networkx_nodes(G, pos, nodelist=[node], node_color=color,
                              node_size=1000, alpha=0.9, ax=ax)

    for u, v, d in G.edges(data=True):
        etype = d.get('label', '')
        color = '#8b949e'
        for key, c in transport_colors.items():
            if key in etype.upper():
                color = c
                break
        nx.draw_networkx_edges(G, pos, edgelist=[(u, v)], edge_color=color,
                              arrows=True, arrowsize=20, width=2.5, alpha=0.8, ax=ax)

    # Node labels
    display_labels = {}
    for node in G.nodes():
        lbl = node_labels_map.get(node, '')
        for key in hub_colors:
            if key in lbl.upper():
                display_labels[node] = f"{node}\n({key})"
                break
        if node not in display_labels:
            display_labels[node] = node

    nx.draw_networkx_labels(G, pos, display_labels, font_size=9,
                           font_color='white', font_weight='bold', ax=ax)

    # Edge weight labels
    edge_labels = {(u, v): f"{d.get('label','')}\nw={d.get('weight','')}"
                   for u, v, d in G.edges(data=True)}
    nx.draw_networkx_edge_labels(G, pos, edge_labels, font_size=7,
                                 font_color='#8b949e', ax=ax)

    ax.set_facecolor('#0d1117')
    ax.set_title('Multi-Modal Logistics Network (AIR → SEA → LAND)',
                color='white', fontsize=14, pad=15)
    legend = [mpatches.Patch(color=c, label=k) for k, c in
              {**hub_colors, **transport_colors}.items()]
    ax.legend(handles=legend, loc='upper left', facecolor='#161b22',
             edgecolor='#30363d', labelcolor='white', fontsize=9, ncol=2)

    plt.tight_layout()
    plt.savefig(f'{IMG_DIR}/usecase_logistics.png', dpi=150, bbox_inches='tight',
                facecolor='#0d1117', edgecolor='none')
    plt.close()
    print("  -> usecase_logistics.png")
else:
    print("  -> Logistics data not available, generating static diagram")
    # Generate a static diagram from known topology
    fig, ax = plt.subplots(figsize=(12, 8))
    fig.patch.set_facecolor('#0d1117')

    G = nx.DiGraph()
    nodes_pos = {
        '1\n(MAINHUB)': (0.5, 0), '2\n(USHUB)': (0.3, 0.35), '3\n(USHUB)': (0.7, 0.35),
        '4\n(SEAHUB)': (0.5, 0.55), '5\n(LANDHUB)': (0.25, 0.75), '6\n(LANDHUB)': (0.75, 0.75),
        '7\n(SPOKE)': (0.5, 1.0)
    }
    edges = [('1\n(MAINHUB)', '2\n(USHUB)', 'AIR', 3), ('1\n(MAINHUB)', '3\n(USHUB)', 'AIR', 5),
             ('2\n(USHUB)', '4\n(SEAHUB)', 'AIR', 4), ('3\n(USHUB)', '4\n(SEAHUB)', 'AIR', 3),
             ('4\n(SEAHUB)', '5\n(LANDHUB)', 'SEA', 8), ('4\n(SEAHUB)', '6\n(LANDHUB)', 'SEA', 9),
             ('5\n(LANDHUB)', '7\n(SPOKE)', 'LAND', 5), ('6\n(LANDHUB)', '7\n(SPOKE)', 'LAND', 7)]

    hub_colors = {'MAINHUB': '#ef4444', 'USHUB': '#f97316', 'SEAHUB': '#3b82f6',
                  'LANDHUB': '#22c55e', 'SPOKE': '#a78bfa'}
    transport_colors = {'AIR': '#ef4444', 'SEA': '#3b82f6', 'LAND': '#22c55e'}

    for n in nodes_pos:
        G.add_node(n)
    for src, tgt, mode, w in edges:
        G.add_edge(src, tgt, mode=mode, weight=w)

    for node in G.nodes():
        color = '#8b949e'
        for key, c in hub_colors.items():
            if key in node:
                color = c
                break
        nx.draw_networkx_nodes(G, nodes_pos, nodelist=[node], node_color=color,
                              node_size=1200, alpha=0.9, ax=ax)

    for u, v, d in G.edges(data=True):
        color = transport_colors.get(d['mode'], '#8b949e')
        nx.draw_networkx_edges(G, nodes_pos, edgelist=[(u, v)], edge_color=color,
                              arrows=True, arrowsize=25, width=3, alpha=0.8, ax=ax)

    nx.draw_networkx_labels(G, nodes_pos, font_size=10, font_color='white',
                           font_weight='bold', ax=ax)
    edge_labels = {(u, v): f"{d['mode']} (w={d['weight']})" for u, v, d in G.edges(data=True)}
    nx.draw_networkx_edge_labels(G, nodes_pos, edge_labels, font_size=8,
                                 font_color='#8b949e', ax=ax)

    ax.set_facecolor('#0d1117')
    ax.set_title('Multi-Modal Logistics Network (AIR → SEA → LAND)',
                color='white', fontsize=14, pad=15)
    legend = [mpatches.Patch(color=c, label=k) for k, c in
              {**hub_colors, **transport_colors}.items()]
    ax.legend(handles=legend, loc='upper left', facecolor='#161b22',
             edgecolor='#30363d', labelcolor='white', fontsize=9, ncol=2)
    plt.tight_layout()
    plt.savefig(f'{IMG_DIR}/usecase_logistics.png', dpi=150, bbox_inches='tight',
                facecolor='#0d1117', edgecolor='none')
    plt.close()
    print("  -> usecase_logistics.png (static)")

# ─────────────────────────────────────────────────────────────
# 4. WIKIPEDIA — Friends graph with labels
# ─────────────────────────────────────────────────────────────
print("Generating wikipedia graph image...")
wiki_data = run_query("""
    GRAPH wiki_graph
    MATCH (a)-[e]->(b)
    RETURN a.node AS source, a.label AS src_label, e.LABEL AS edge_type,
           b.node AS target, b.label AS tgt_label, a.age AS src_age, b.age AS tgt_age
""")

if wiki_data and wiki_data.get('records'):
    fig, ax = plt.subplots(figsize=(10, 7))
    fig.patch.set_facecolor('#0d1117')

    G = nx.DiGraph()
    node_info = {}
    for r in wiki_data['records']:
        src, tgt = r['source'], r['target']
        G.add_edge(src, tgt, label=r.get('edge_type', ''))
        node_info[src] = {'label': r.get('src_label', ''), 'age': r.get('src_age', '')}
        node_info[tgt] = {'label': r.get('tgt_label', ''), 'age': r.get('tgt_age', '')}

    pos = nx.spring_layout(G, k=3, seed=42)

    gender_colors = {}
    for node, info in node_info.items():
        lbl = str(info.get('label', ''))
        if 'MALE' in lbl.upper():
            gender_colors[node] = '#58a6ff'
        elif 'FEMALE' in lbl.upper():
            gender_colors[node] = '#f472b6'
        else:
            gender_colors[node] = '#8b949e'

    for node in G.nodes():
        color = gender_colors.get(node, '#8b949e')
        nx.draw_networkx_nodes(G, pos, nodelist=[node], node_color=color,
                              node_size=1200, alpha=0.9, ax=ax)

    edge_type_colors = {'Friend': '#22c55e', 'Family': '#f97316'}
    for u, v, d in G.edges(data=True):
        lbl = d.get('label', '')
        color = '#8b949e'
        for key, c in edge_type_colors.items():
            if key in lbl:
                color = c
                break
        nx.draw_networkx_edges(G, pos, edgelist=[(u, v)], edge_color=color,
                              arrows=True, arrowsize=20, width=2, alpha=0.7, ax=ax)

    labels = {n: f"{n}\nage:{node_info.get(n, {}).get('age', '?')}" for n in G.nodes()}
    nx.draw_networkx_labels(G, pos, labels, font_size=9, font_color='white',
                           font_weight='bold', ax=ax)
    edge_labels = {(u, v): d.get('label', '') for u, v, d in G.edges(data=True)}
    nx.draw_networkx_edge_labels(G, pos, edge_labels, font_size=8,
                                 font_color='#8b949e', ax=ax)

    ax.set_facecolor('#0d1117')
    ax.set_title('Wikipedia Example — People, Interests & Relations',
                color='white', fontsize=14, pad=15)
    legend = [mpatches.Patch(color='#58a6ff', label='Male'),
              mpatches.Patch(color='#f472b6', label='Female'),
              mpatches.Patch(color='#22c55e', label='Friend'),
              mpatches.Patch(color='#f97316', label='Family')]
    ax.legend(handles=legend, loc='upper left', facecolor='#161b22',
             edgecolor='#30363d', labelcolor='white', fontsize=10)
    plt.tight_layout()
    plt.savefig(f'{IMG_DIR}/usecase_wikipedia.png', dpi=150, bbox_inches='tight',
                facecolor='#0d1117', edgecolor='none')
    plt.close()
    print("  -> usecase_wikipedia.png")
else:
    print("  -> Wiki graph not available, skipping")

print("\nDone! Generated images in", IMG_DIR)
print("Files:", os.listdir(IMG_DIR))
