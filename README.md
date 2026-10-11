# SuperRender (v0.1.0)

Biblioteca leve de jogos para Windows, com inicialização **Normal** ou **Otimizada**.

### Uso

1. Tenha Python 3.10+ instalado (sem dependências externas obrigatórias).
2. Execute `iniciar.bat` no Windows; o navegador abrirá o app local.
3. Clique em **Buscar jogos** para descobrir jogos compatíveis ou **Adicionar jogo** e informe o caminho do `.exe`.
4. Escolha **Normal** ou **Otimizado**. A biblioteca é local e não é enviada ao GitHub.
5. Para obter alterações futuras no repositório, `git pull` ou `atualizar.bat`.

### Otimização experimental

O perfil **Otimizado** tenta ativar o plano de energia de alto desempenho durante a execução, restaurando o plano anterior quando o processo inicial encerra. Se `psutil` estiver instalado, tenta alterar a prioridade para **acima do normal**. Nenhum arquivo do jogo é alterado. A restauração pode não acontecer se o aplicativo for encerrado de maneira forçada ou o computador desligar; nesse caso, restaure o plano de energia pelas opções do Windows. O programa **não garante** aumento de FPS nem consegue alterar a renderização de jogos DirectX por conta própria.

### Segurança

- O servidor abre apenas em `127.0.0.1` com porta aleatória.
- Apenas executáveis cadastrados localmente podem ser iniciados.
- Dados ficam em `%LOCALAPPDATA%\SuperRender\library.json` e não no Git.
- Evite usar perfis experimentais em jogos competitivos/anticheat.

### Próximas etapas

Benchmark de FPS/frametime, importadores Steam/Epic, perfis por jogo, integração específica com NBA 2K20 e melhorias gráficas verdadeiras com medição A/B.
