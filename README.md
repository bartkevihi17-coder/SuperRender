# SuperRender

**v0.3.2 · Biblioteca de jogos e laboratório de desempenho para Windows**

Aplicativo nativo escrito em Python e Qt (PySide6). Não depende de navegador, HTML, WebGPU ou servidor local. Jogos, favoritos e preferências são armazenados somente no computador do usuário, em `%LOCALAPPDATA%\SuperRender`.

## Biblioteca

O SuperRender procura automaticamente jogos da Steam, Epic Games, GOG, Riot Games, atalhos do Windows e diretórios conhecidos de instalações em unidades locais. Também permite adicionar manualmente um jogo quando a instalação não é detectada. Usa capas disponíveis da Steam, ícones dos executáveis e uma imagem genérica quando não há arte.

A interface traz um menu recolhível, busca, galeria de destaques, notificações e abertura animada com a figurinha centralizada. Cada card tem **Play** e uma **engrenagem** para configurar o modo de inicialização.

## Quatro perfis

| Perfil | NBA 2K20 | Outros jogos |
| --- | --- | --- |
| Normal | Sem alterações | Sem alterações |
| Levemente otimizado | Configurações conservadoras e prioridade acima do normal | Somente prioridade de processo, quando permitida |
| Otimizado | Configuração experimental de 960×540 e efeitos gráficos reduzidos | Somente prioridade de processo, quando permitida |
| Potato | Configuração experimental de 640×480 e qualidade mínima | Somente prioridade de processo, quando permitida |

O programa **não promete ganhos fixos de FPS**. Adaptações gráficas são específicas de cada jogo. O NBA 2K20 usa seu arquivo `VideoSettings.cfg`, sempre com cópia de segurança e restauração verificável. Jogos com anticheat não recebem alterações automáticas de prioridade.

Você pode escolher um perfil principal e marcar **abrir sem perguntar novamente**. A engrenagem permite alterar essa escolha depois.

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
.\dist\SuperRender.exe
```

O arquivo compilado também está no repositório em `dist/SuperRender.exe`. Se preferir usar o código-fonte, execute `iniciar.bat` com Python 3.10 ou superior. Compile com `build.bat`.

## Código e licenças

- `app/qt_gui.py`: interface principal e iniciação de jogos.
- `app/ui_widgets.py`: animações, splash, galeria e controles Qt.
- `app/fps_overlay.py`: atalho global Ctrl + 7, captura e overlay Qt.
- `app/rtss_backend.py`: integração exclusiva do nosso código com OSD RTSS e provisionamento opcional via WinGet.
- `app/optimization.py`: perfis específicos, backups e restauração.
- `app/discovery.py`, `app/artwork.py`, `app/library.py`, `app/launcher.py`: descoberta, imagens, persistência e execução.
- `tests/`: testes que não abrem jogos.
- `third_party/PresentMon-LICENSE.txt`: aviso de licença do PresentMon redistribuído.

Para executar os testes:

```powershell
python -m unittest discover -s tests -v
```

**Não alteramos os arquivos executáveis dos jogos, DRM, saves ou sistemas de anticheat.** A medição com RTSS depende das APIs e da compatibilidade disponibilizadas pelo software de terceiros.
