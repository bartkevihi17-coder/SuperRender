# SuperRender — aplicativo desktop nativo

**SuperRender v0.2** é uma biblioteca de jogos para **Windows 10/11**, escrita em **Python + Tkinter**. É um aplicativo local: **não executa um servidor HTTP, não depende de HTML nem abre uma página no navegador**.

> Projeto experimental e em desenvolvimento. O objetivo atual é organizar e executar jogos. A opção **Otimizado** ainda **não** altera os gráficos, o DirectX, os shaders nem garante aumento de FPS.

## Recursos

- Interface escura nativa, busca, favoritos, filtros e detalhes.
- Identificação automática das bibliotecas da **Steam** (incluindo bibliotecas em outros discos), **Epic Games**, **GOG**, **Riot Games**, atalhos do menu Iniciar/Área de Trabalho e instalações em pastas de jogos.
- Unidades e pastas detectadas no **computador do usuário** — não existem caminhos fixos do computador do desenvolvedor.
- Capas oficiais de jogos da Steam quando disponíveis, e ícones associados aos arquivos EXE/atalhos em outros casos. Sem capa disponível, mostra uma arte genérica claramente identificada.
- Dois comandos por jogo: **Normal** e **Otimizado**.
- Armazenamento local em \`%LOCALAPPDATA%\\SuperRender\\library.json\`, fora do repositório.
- Suporte a jogos adicionados manualmente quando não existe um manifesto/atalho detectável.

## Rodar a partir do código

Requer Windows e Python 3.10 ou superior, com Tkinter (vem no instalador oficial de Python para Windows).

Abra \`iniciar.bat\` (janela sem console) ou use \`python run.py\` para ver erros no terminal.

A detecção começa automaticamente na primeira execução. Para procurar instalações novas, clique em **Buscar jogos** ou aperte **F5**. \`Ctrl+F\` abre a busca.

## Criar executável para distribuir

No Windows execute \`build.bat\`. Ele instala o empacotador PyInstaller e produz um executável único em:

\`dist\\SuperRender.exe\`

Este executável não exige que o computador de destino tenha Python instalado. Ele é gerado **localmente**, não é enviado por padrão ao GitHub.

## Como funciona o modo otimizado hoje

- Para executáveis Windows elegíveis, solicita prioridade **acima do normal**.
- Para jogos abertos via protocolo de launcher Steam/Epic, tenta reconhecer o executável instalado e aguarda o processo para ajustar sua prioridade temporariamente.
- Evita automaticamente ajustes em alguns jogos competitivos com anticheat.
- Não modifica arquivos do jogo, não injeta DLL, não força drivers e não contorna DRM.
- Não promete ganhos de FPS. A medição de FPS e o aprimoramento da renderização são próximos marcos.

## Limitações honestas

Não existe API universal para identificar **todos** os jogos, inclusive executáveis sem instalador ou manifesto em pastas arbitrárias. Os detectores cobrem as origens comuns; **Adicionar jogo** é o recurso reserva. Alguns launchers e ícones podem não ser identificados, e imagens online da Steam exigem internet. Instalações de terceiros fora dos diretórios convencionais podem precisar de adição manual.

Os caminhos, favoritos e o histórico ficam no computador de cada usuário. Não são exportados nem coletados automaticamente.

## Desenvolvimento

Estrutura modular:

- \`app/discovery.py\`: importadores independentes de bibliotecas e locais.
- \`app/library.py\`: persistência e reconciliação.
- \`app/artwork.py\`: capas e ícones locais.
- \`app/launcher.py\`: modos de inicialização.
- \`app/gui.py\`: janela nativa.
- \`tests/\`: testes locais do núcleo.

Para atualizar a pasta Git: \`git pull --ff-only\` ou \`atualizar.bat\`. Após um pull, reinicie o programa para usar o código novo.

**NBA 2K20 é apenas um dos jogos usados para validação**, sem configurações ou regras exclusivas da máquina de desenvolvimento.
