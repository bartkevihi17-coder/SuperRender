# SuperRender

**v0.6.0 · Biblioteca de jogos e laboratório de desempenho para Windows**

Aplicativo nativo escrito em Python e Qt (PySide6). Não depende de navegador, HTML, WebGPU ou servidor local. Jogos, favoritos e preferências são armazenados somente no computador do usuário, em `%LOCALAPPDATA%\SuperRender`.

## Biblioteca

O SuperRender procura automaticamente jogos da Steam, Epic Games, GOG, Riot Games, atalhos do Windows e diretórios conhecidos de instalações em unidades locais. Também permite adicionar manualmente um jogo quando a instalação não é detectada. Usa capas disponíveis da Steam, ícones dos executáveis e uma imagem genérica quando não há arte.

A interface traz um menu recolhível, busca, galeria de destaques, notificações e abertura animada com a figurinha centralizada. Cada card tem **Play** e uma **engrenagem** para configurar o modo de inicialização.

## Cinco perfis

| Perfil | NBA 2K20 | Outros jogos |
| --- | --- | --- |
| Normal | Sem alterações | Sem alterações |
| Levemente otimizado | Configurações conservadoras e prioridade acima do normal | Somente prioridade de processo, quando permitida |
| Otimizado | Configuração experimental de 960×540 e efeitos gráficos reduzidos | Somente prioridade de processo, quando permitida |
| Potato | Configuração experimental de 640×480 e qualidade mínima | Somente prioridade de processo, quando permitida |
| Render (Beta) | Quality Adapter alto + Frame Generation externo | Preserva o preset; FG externo quando compativel |

O programa **não promete ganhos fixos de FPS**. Adaptações gráficas são específicas de cada jogo. O NBA 2K20 usa seu arquivo `VideoSettings.cfg`, sempre com cópia de segurança e restauração verificável. Jogos com anticheat não recebem alterações automáticas de prioridade.

Você pode escolher um perfil principal e marcar **abrir sem perguntar novamente**. A engrenagem permite alterar essa escolha depois.

**Render (Beta) v0.6:** o caminho experimental de Frame Generation foi redesenhado para **nao injetar DLL no jogo**. O SuperRender inicia um helper proprio em processo separado, captura apenas a janela do jogo com Windows Graphics Capture, estima movimento em compute shaders D3D11 e apresenta uma cadencia sintetizada em um overlay click-through. O jogo continua sendo o responsavel pelos frames reais; o SuperRender mede separadamente FPS capturado/real, FPS apresentado, FPS gerado, custo do motor e latencia.

A politica visual e **quality-first**. O nucleo de Frame Generation e geral; configuracoes de qualidade ficam em `Quality Adapters` plugaveis. Quando existe um adaptador validado, o Render aplica temporariamente um preset alto e reversivel sem reduzir WIDTH/HEIGHT. O NBA 2K20 e apenas o primeiro adaptador: usa torcida/jogadores/texturas em alta, sombras High (nao Ultra), efeitos visuais relevantes ligados e fullscreen-windowed para o compositor externo. Ao fechar o jogo, o backup anterior e restaurado. Jogos sem adaptador mantem suas configuracoes atuais.

Em GPUs antigas, o helper usa uma busca de movimento mais barata (blocos maiores e raio menor); hardware mais forte recebe uma estimativa mais refinada. A meta padrao e 60 Hz de saida, mas **quadros gerados nao sao chamados de FPS reais**: a simulacao e a resposta aos comandos continuam limitadas pelos frames reais produzidos pelo jogo.

O modo Render continua recomendado para **jogos offline**. Por politica do SuperRender, titulos reconhecidos como competitivos/protegidos nao recebem o backend experimental. Nao ha mecanismo de bypass de anticheat, escolha arbitraria de processos ou carregamento de DLL em jogos.

## Play e Interromper (0.3.3)

- O botao **Play** abre o jogo no perfil escolhido.
- Enquanto o SuperRender identificar o processo de um jogo que **ele mesmo
  iniciou**, o botao vira **Interromper**, com destaque vermelho.
- Interromper solicita primeiro o fechamento normal da janela do jogo
  (\`WM_CLOSE\`), permitindo que o jogo encerre da forma habitual.
- Se ele nao responder, pergunta explicitamente antes de forcar o encerramento:
  **progresso nao salvo podera ser perdido**.
- O comando verifica o **PID e o caminho completo do executavel**. Nao encerra
  a Steam, a Epic ou outros processos apenas por estarem relacionados ao jogo.
- Se a instalacao nao informar o executavel real, o SuperRender sinaliza
  quando nao consegue controlar o processo. O atalho de iniciacao continua
  funcionando quando o launcher permitir.

### Corrigido: backup pendente do NBA 2K20

Se o jogo ja devolveu \`VideoSettings.cfg\` ao estado original, o SuperRender
reconhece os arquivos identicos por SHA-256 e remove somente o registro
pendente, sem alterar o jogo.

Quando a configuracao atual difere tanto da original quanto da otimizada,
o usuario escolhe **Manter configuracao atual** ou **Restaurar backup anterior**.
As duas versoes sao preservadas e a resolucao nunca e forcada em silencio.
Isso evita bloquear o Play quando o jogo muda seu proprio CFG ao sair.

## FPS sobre os jogos, inclusive tela cheia

O SuperRender apresenta um contador no canto superior esquerdo, com **Ctrl + 7** para mostrar ou esconder. O contador inicia junto com jogos abertos pelo SuperRender e desaparece quando o jogo deixa de estar em primeiro plano ou é fechado.

**Dois caminhos de exibição:**

1. **RTSS (RivaTuner Statistics Server)** para sobreposição **dentro do pipeline gráfico do jogo**, inclusive muitos jogos em tela cheia exclusiva. O SuperRender utiliza o SDK de memória compartilhada para solicitar `FPS: <FR>`: o número é medido pelo próprio RTSS. O programa não modifica o perfil global do RTSS.
2. **Sobreposição própria Qt** como alternativa para jogos em janela ou janela sem bordas. Nesse caminho, o FPS vem da medição de quadros do PresentMon (embutido no `.exe`) ou de dados RTSS, quando disponíveis. Sem medição válida, mostra `FPS --`, não um valor fictício.

**Distribuição sem downloads manuais:** se o RTSS já estiver instalado, o SuperRender pode iniciá-lo automaticamente antes do jogo. Caso não esteja, oferece **instalação automática pelo WinGet**, com consentimento do usuário e aviso de que o RTSS é um software de terceiros. A instalação pode exigir internet, permissões administrativas e aceitação dos termos. Não hospedamos nem incluímos o instalador proprietário do RTSS no repositório.

O fornecedor oficial do RTSS é [Guru3D / Unwinder](https://www.guru3d.com/download/rtss-rivatuner-statistics-server-download/), e o pacote WinGet utilizado é `Guru3D.RTSS`.

**Limitações:** alguns anticheats e jogos com proteções especiais não permitem esse tipo de OSD. O SuperRender não tenta burlá-los. Outros modos gráficos podem ter limitações próprias do driver ou RTSS. O uso de uma janela sobreposta tradicional não garante visibilidade em tela cheia exclusiva.

## Executar e atualizar

Para máquinas com o executável distribuído, basta abrir `SuperRender.exe`. O programa inclui Python, Qt e PresentMon, sem instalações manuais de dependências. Para atualizar a versão local via Git:

```powershell
cd "$env:USERPROFILE\Desktop\SuperRender"
git pull --ff-only
.\iniciar.bat
```

O arquivo compilado também está no repositório em `dist/SuperRender.exe`. Em um **clone Git de desenvolvimento**, `iniciar.bat` prefere o código-fonte para que um `git pull` tenha efeito imediatamente. Em pacotes distribuídos sem a pasta `.git`, ele usa o executável compilado. O workflow Windows recompila o backend nativo e o `SuperRender.exe`.

## Código e licenças

- `app/qt_gui.py`: interface principal e iniciação de jogos.
- `app/ui_widgets.py`: animações, splash, galeria e controles Qt.
- `app/fps_overlay.py`: atalho global Ctrl + 7, captura e overlay Qt.
- `app/rtss_backend.py`: integração exclusiva do nosso código com OSD RTSS e provisionamento opcional via WinGet.
- `app/optimization.py`: perfis específicos, backups e restauração.
- `app/render_engine.py`: planejamento adaptativo do Render Beta, selecao de backend e registro de metricas.
- `app/render_backend.py`: inicia/verifica o helper externo e le telemetria do Frame Generation.
- `app/quality_adapters.py`: presets quality-first reversiveis e plugaveis por jogo.
- `native/framegen/`: helper proprio WGC/D3D11 com estimativa de movimento e interpolacao.
- `app/discovery.py`, `app/artwork.py`, `app/library.py`, `app/launcher.py`: descoberta, imagens, persistência e execução.
- `tests/`: testes que não abrem jogos.
- `third_party/PresentMon-LICENSE.txt`: aviso de licença do PresentMon redistribuído.
- `THIRD_PARTY.md`: componentes externos e origem dos binarios distribuidos.

Para executar os testes:

```powershell
python -m unittest discover -s tests -v
```

**Não alteramos os executáveis dos jogos, DRM, saves ou sistemas de anticheat.** O Frame Generation atual roda em processo separado e usa captura de janela; nao injeta DLL nem grava na memoria do jogo. A medicao com RTSS depende das APIs e da compatibilidade disponibilizadas pelo software de terceiros.

O SuperRender e distribuido sob **GNU GPL v3**. Consulte `LICENSE` e `THIRD_PARTY.md`.
