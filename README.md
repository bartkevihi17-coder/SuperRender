# SuperRender

**SuperRender 0.3 — biblioteca e otimizador experimental de jogos para Windows.**

Aplicativo **nativo em Python + Qt Widgets (PySide6)**. Nao depende de navegador, HTML, React, servidor local nem WebGPU. Suas preferencias e seus jogos ficam **no proprio PC**.

> O objetivo e testar melhorias reais de desempenho sem prometer resultados irreais. O software nao substitui uma GPU compativel ou GPU cloud. Imagens bonitas e efeitos na biblioteca nao sao renderizados durante a partida (a janela e minimizada e as animacoes pausam).

## Principais funcoes

- Detecta jogos de Steam, Epic Games, GOG, Riot Games, atalhos do Windows e outras bibliotecas em unidades instaladas; cadastro manual disponivel como recurso reserva.
- Importa capas oficiais da Steam e icones de executaveis (ou usa uma arte generica quando nao ha imagem disponivel).
- Sidebar recolhivel com selecao animada, cards, busca, destaques que expandem ao passar o mouse, fundo gradiente sutil, notificacoes e splash com logo estilo adesivo.
- Apenas um botao **Play** por jogo; ao lado, **engrenagem** de preferencias.
- Ao clicar Play, oferece quatro perfis: **Normal**, **Levemente otimizado**, **Otimizado** e **Potato**.
- Dois interruptores independentes: usar o perfil como principal e pular o dialogo nas proximas aberturas. Marcando "pular dialogo", o perfil escolhido tambem passa a ser o principal.
- A engrenagem SEMPRE permite mudar a preferencia, mesmo se o Play foi configurado para abertura direta.

## O que os perfis fazem (0.3)

| Perfil | Processo Windows | NBA 2K20 | Demais jogos |
| --- | --- | --- | --- |
| Normal | Sem alteracoes | Configuracao atual intocada | Normal |
| Levemente otimizado | Prioridade acima do normal (exceto anticheat) | Ajustes internos conservadores, mantendo resolucao atual | Apenas prioridade |
| Otimizado | Prioridade acima do normal | Configuracao experimental 960x540, efeitos, crowd, sombras, shader detail baixos | Apenas prioridade |
| Potato | Prioridade alta (nunca tempo real) | Configuracao experimental 640x480, minima qualidade, imagem pode perder nitidez e proporcao | Apenas prioridade |

**Importante:** estas alteracoes nao garantem aumento de FPS. Em jogos competitivos com anticheat, nao modifica a prioridade; nem faz injecao de DLL. Os modos mais fortes para jogos sem adaptador NAO reduzem graficos.

O programa identifica o NBA 2K20 pelo executavel e usa o **VideoSettings.cfg** no local documentado pelo jogo: \`%APPDATA%\2K Sports\NBA 2K20\VideoSettings.cfg\`. O caminho nao depende de qual disco contem o jogo. Antes de alterar esse arquivo, salva copia em \`%LOCALAPPDATA%\SuperRender\backups\` e cria registro de recuperacao em \`sessions\`.

Ao detectar que o jogo encerrou, tenta restaurar o estado original **exatamente**. Se o jogo editar o arquivo durante a partida, o SuperRender NAO apaga as alteracoes: mantem o backup para revisao. Pela **engrenagem** e possivel fazer uma restauracao confirmada, preservando uma copia do novo estado antes de restaurar. Se o app encerrar a forca, tenta se recuperar quando reabrir.

**Nao altera os arquivos .exe, mods, saves ou diretorios de instalacao dos jogos.**

## Instalacao

### Windows com Python

Requer Python 3.10+ e internet apenas para instalar a interface grafica na primeira vez:

\`\`\`powershell
git pull
.\iniciar.bat
\`\`\`

\`iniciar.bat\` abre o executavel em \`dist\`, se presente. Se nao houver executavel, prepara a dependencia **PySide6-Essentials** e abre \`run.pyw\`.

### Windows sem Python

Baixe \`dist/SuperRender.exe\` do repositório (quando publicado) e execute. O PyInstaller incorpora Python e bibliotecas necessarias ao .exe.

### Gerar binario local

Execute \`build.bat\`. A compilacao roda em prioridade reduzida para interferir menos em aplicativos abertos; exige Python e pip.

## Desenvolvimento

- \`app/qt_gui.py\`: janela principal, biblioteca e botoes.
- \`app/ui_widgets.py\`: controles/efeitos visuais de desktop.
- \`app/ui_dialogs.py\`: seletor de perfil e switches persistentes.
- \`app/optimization.py\`: adaptadores graficos, backups e restauracao.
- \`app/launcher.py\`: inicio de jogos e prioridade de processo.
- \`app/discovery.py\`: importadores de jogos independentes de caminhos fixos.
- \`app/artwork.py\`: busca de capas e extracao local de icones.
- \`app/library.py\`: arquivo JSON de biblioteca por usuario e preferencias.
- \`tests\`: testes automatizados sem executar jogos reais.

\`\`\`powershell
python -m unittest discover -s tests -v
python run.py
\`\`\`

## Requisitos e limites

O adaptador NBA 2K20 nao garante que qualquer resolucao sera aceita pelo driver ou monitor; se falhar, selecione um perfil menos agressivo. 640x480 e um recurso de emergencia recomendado na documentacao do proprio NBA. Se um sistema nao reconhecer a resolucao, retorne ao Normal ou restaure o backup.

O projeto foi testado inicialmente numa maquina antiga Windows 10 com GT 730 e i5. A deteccao de jogos, imagens e configuracoes foi projetada para maquinas diferentes, mas nenhum scanner consegue localizar 100% dos jogos instalados em pastas arbitrarias sem rastrear todo o armazenamento. A adicao manual permanece opcional.

**O SuperRender e um projeto experimental; qualquer ganho de desempenho precisa ser medido em partida, comparando FPS e frametimes.**
