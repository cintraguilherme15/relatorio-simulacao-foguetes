"""Gera automaticamente um relatório em PDF da simulação de voo de um foguete.

Uso:  python gerar_relatorio.py foguete.json
"""
import json
import sys
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from fpdf import FPDF
from rocketpy import Environment, Flight, Rocket, SolidMotor


def montar_simulacao(cfg):
    lan, fog, mot = cfg["lancamento"], cfg["foguete"], cfg["motor"]

    env = Environment(latitude=lan["latitude"], longitude=lan["longitude"], elevation=lan["altitude_m"])
    env.set_atmospheric_model(type="standard_atmosphere")

    altura_motor = mot["numero_graos"] * (mot["altura_grao_m"] + mot["separacao_graos_m"])
    motor = SolidMotor(
        thrust_source=mot["curva_empuxo"],
        dry_mass=mot["massa_seca_kg"],
        dry_inertia=(0.01, 0.01, 0.0005),
        nozzle_radius=mot["raio_bocal_m"],
        grain_number=mot["numero_graos"],
        grain_density=mot["densidade_grao_kgm3"],
        grain_outer_radius=mot["raio_externo_grao_m"],
        grain_initial_inner_radius=mot["raio_interno_grao_m"],
        grain_initial_height=mot["altura_grao_m"],
        grain_separation=mot["separacao_graos_m"],
        grains_center_of_mass_position=altura_motor / 2,
        center_of_dry_mass_position=altura_motor / 2,
        nozzle_position=0,
        burn_time=mot["curva_empuxo"][-1][0],
        coordinate_system_orientation="nozzle_to_combustion_chamber",
    )

    rocket = Rocket(
        radius=fog["raio_m"],
        mass=fog["massa_sem_motor_kg"],
        inertia=tuple(fog["inercia_kgm2"]),
        power_off_drag=fog["cd"],
        power_on_drag=fog["cd"],
        center_of_mass_without_motor=fog["cg_sem_motor_m"],
        coordinate_system_orientation="tail_to_nose",
    )
    rocket.add_motor(motor, position=mot["posicao_m"])
    c = cfg["coifa"]
    rocket.add_nose(length=c["comprimento_m"], kind=c["tipo"], position=c["posicao_m"])
    a = cfg["aletas"]
    rocket.add_trapezoidal_fins(
        n=a["quantidade"], root_chord=a["corda_raiz_m"], tip_chord=a["corda_ponta_m"],
        span=a["envergadura_m"], position=a["posicao_m"], sweep_length=a["enflechamento_m"],
    )
    p = cfg["paraquedas"]
    rocket.add_parachute("Principal", cd_s=p["cd_area_m2"], trigger="apogee", sampling_rate=100, lag=p["atraso_s"])

    margem = rocket.static_margin(0)
    if margem < 1.0:
        raise ValueError(
            f"Margem estática de {margem:.2f} calibres: o foguete está instável e a simulação não foi feita. "
            "Aumente as aletas, mova-as para trás ou desloque massa para a coifa."
        )

    voo = Flight(rocket=rocket, environment=env, rail_length=lan["trilho_m"],
                 inclination=lan["inclinacao_graus"], heading=lan["direcao_graus"],
                 terminate_on_apogee=False, max_time=600)
    return env, rocket, voo


def resultados(env, rocket, voo):
    return {
        "Apogeu (acima do solo)": f"{voo.apogee - env.elevation:.1f} m",
        "Tempo até o apogeu": f"{voo.apogee_time:.2f} s",
        "Velocidade máxima": f"{voo.max_speed:.1f} m/s (Mach {voo.max_mach_number:.2f})",
        "Velocidade de saída do trilho": f"{voo.out_of_rail_velocity:.1f} m/s",
        "Margem estática inicial": f"{rocket.static_margin(0):.2f} calibres",
        "Margem de estabilidade na saída do trilho": f"{voo.out_of_rail_stability_margin:.2f} calibres",
        "Tempo total de voo": f"{voo.t_final:.1f} s",
    }


def alertas(env, rocket, voo):
    avisos = []
    if voo.out_of_rail_velocity < 15:
        avisos.append("Velocidade de saída do trilho abaixo de 15 m/s: risco de voo instável.")
    m = voo.out_of_rail_stability_margin
    if m < 1.5:
        avisos.append(f"Margem de estabilidade baixa ({m:.2f} cal): foguete pode ficar instável.")
    elif m > 3.0:
        avisos.append(f"Margem de estabilidade alta ({m:.2f} cal): foguete superestável, sensível a vento.")
    return avisos or ["Nenhum alerta: parâmetros dentro das faixas usuais."]


def graficos(env, voo, prefixo):
    arquivos = []
    series = [
        ("altitude", voo.z, "Altitude acima do solo (m)", -env.elevation),
        ("velocidade", voo.speed, "Velocidade (m/s)", 0),
        ("estabilidade", voo.stability_margin, "Margem de estabilidade (calibres)", 0),
    ]
    for nome, func, rotulo, ajuste in series:
        dados = func.source
        t_lim = voo.apogee_time * 1.05 if nome == "estabilidade" else dados[-1, 0]
        sel = dados[:, 0] <= t_lim
        fig, ax = plt.subplots(figsize=(7, 3))
        ax.plot(dados[sel, 0], dados[sel, 1] + ajuste, color="#1f4e79")
        ax.set_xlabel("Tempo (s)")
        ax.set_ylabel(rotulo)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        caminho = f"{prefixo}_{nome}.png"
        fig.savefig(caminho, dpi=150)
        plt.close(fig)
        arquivos.append(caminho)
    return arquivos


def gerar_pdf(cfg, res, avisos, imagens, saida):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, f"Relatório de Simulação - {cfg['nome']}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, f"Gerado em {datetime.now():%d/%m/%Y %H:%M} com RocketPy", new_x="LMARGIN", new_y="NEXT")
    if cfg.get("observacao"):
        pdf.cell(0, 6, cfg["observacao"], new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Resultados principais", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for k, v in res.items():
        pdf.cell(95, 6, k, border=1)
        pdf.cell(0, 6, v, border=1, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Alertas", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    for a in avisos:
        pdf.multi_cell(0, 6, f"- {a}", new_x="LMARGIN", new_y="NEXT")

    for img in imagens:
        if pdf.get_y() > 200:
            pdf.add_page()
        pdf.image(img, w=180)
    pdf.output(saida)


def main():
    arquivo = sys.argv[1] if len(sys.argv) > 1 else "foguete.json"
    try:
        with open(arquivo, encoding="utf-8") as f:
            cfg = json.load(f)
    except FileNotFoundError:
        sys.exit(f"Erro: arquivo '{arquivo}' não encontrado.")
    except json.JSONDecodeError as e:
        sys.exit(f"Erro no arquivo '{arquivo}' (linha {e.lineno}): confira vírgulas e aspas.")
    try:
        env, rocket, voo = montar_simulacao(cfg)
    except KeyError as e:
        sys.exit(f"Erro: o campo {e} está faltando no arquivo '{arquivo}'.")
    except ValueError as e:
        sys.exit(f"Atenção: {e}")
    res = resultados(env, rocket, voo)
    avisos = alertas(env, rocket, voo)
    prefixo = cfg["nome"].replace(" ", "_")
    imagens = graficos(env, voo, prefixo)
    saida = f"relatorio_{prefixo}.pdf"
    gerar_pdf(cfg, res, avisos, imagens, saida)
    for k, v in res.items():
        print(f"{k}: {v}")
    print(f"\nRelatório salvo em {saida}")


if __name__ == "__main__":
    main()
