# SuperRender

**v0.5.0 · Biblioteca de jogos e laboratório de desempenho para Windows**

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
| Render (Beta) | Preserva o preset visual restaurado e tenta Frame Generation | Preserva o preset visual; FG nativo quando compatível |

O programa **não promete ganhos fixos de FPS**. Adaptações gráficas são específicas de cada jogo. O NBA 2K20 usa seu arquivo `VideoSettings.cfg`, sempre com cópia de segurança e restauração verificável. Jogos com anticheat não recebem alterações automáticas de prioridade.

Você pode escolher um perfil principal e marcar **abrir sem perguntar novamente**. A engrenagem permite alterar essa escolha depois.

**Render (Beta) v0.5:** agora possui um backend nativo experimental de **Frame Generation para jogos Windows x64/DirectX 11**. O jogo continua renderizando com sua configuracao visual atual/restaurada; o Render nao aplica os cortes de qualidade dos perfis Otimizado/Potato. Depois que o processo abre, o SuperRender mede alguns FPS reais e escolhe automaticamente quantos quadros intermediarios inserir para mirar 60 FPS: por exemplo, ~30 FPS usa 2x e ~22–25 FPS usa 3x. O motor limita o automatico a no maximo tres quadros gerados entre quadros reais (4x de cadencia).

O backend experimental atual e construido a partir do projeto aberto **Lufzy's Frame Generation (LFG)**, fixado em um commit conhecido e modificado pelo script `scripts/patch_lfg.py` para o modo quality-first do SuperRender. Em GPUs antigas, o SuperRender escolhe uma estimativa de movimento mais barata; em GPUs mais fortes usa uma configuracao de maior qualidade. A resolucao visivel do jogo permanece em 100% nesse caminho.

O modo Render e recomendado para **jogos offline**. O SuperRender nao tenta contornar anticheat, nao faz injecao em titulos reconhecidos como protegidos/competitivos e nao oferece um modo de escolher processos ou DLLs arbitrarios. A decisao e registrada em `%LOCALAPPDATA%\\SuperRender\\render_sessions`, separando FPS base, FPS apresentado e quantidade de quadros gerados.

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
- `app/render_backend.py`: configuracao por PID, validacao de integridade e inicializacao restrita do backend DX11.
- `scripts/patch_lfg.py`: patch reproduzivel aplicado ao backend LFG fixado pelo build.
- `app/discovery.py`, `app/artwork.py`, `app/library.py`, `app/launcher.py`: descoberta, imagens, persistência e execução.
- `tests/`: testes que não abrem jogos.
- `third_party/PresentMon-LICENSE.txt`: aviso de licença do PresentMon redistribuído.
- `third_party/LFG-LICENSE.txt` e `THIRD_PARTY.md`: origem/licenca do backend experimental.

Para executar os testes:

```powershell
python -m unittest discover -s tests -v
```

**Não alteramos os arquivos executáveis dos jogos, DRM, saves ou sistemas de anticheat.** O backend DX11 experimental atua somente na memoria do processo do jogo iniciado pelo SuperRender e apenas quando o caminho foi validado; nao ha mecanismo de bypass de anticheat. A medicao com RTSS depende das APIs e da compatibilidade disponibilizadas pelo software de terceiros.

O SuperRender e distribuido sob **GNU GPL v3**. Consulte `LICENSE` e `THIRD_PARTY.md`.
