"""One-accent dark design tokens for SuperRender Qt Widgets."""
PALETTE = {
    "bg": "#0B0E14", "base": "#111722", "panel": "#171F2C",
    "panel2": "#202B3A", "stroke": "#354255", "ink": "#F5F7FC",
    "muted": "#ADBACA", "accent": "#6EA8FE", "dark": "#08111F",
    "pink": "#6EA8FE", "mint": "#6EA8FE", "warm": "#6EA8FE",
}
PROFILE_DESCRIPTIONS = {
    "normal": ("◉", "Configuração original do jogo"),
    "light": ("◐", "Ajustes conservadores"),
    "optimized": ("⚡", "Prioridade para desempenho"),
    "potato": ("▤", "Redução máxima de custo gráfico"),
    "render": ("✦", "Qualidade adaptada e FG experimental"),
}
LAUNCH_STATES = {
    "idle": ("▶  JOGAR · PRONTO", "#6EA8FE"),
    "starting": ("◌  CALIBRANDO / INICIANDO", "#B89CFF"),
    "running": ("■  JOGANDO · INTERROMPER", "#CA6875"),
    "stopping": ("■  ENCERRANDO...", "#856474"),
}
