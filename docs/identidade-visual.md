# Identidade Visual — EmpireMuse

Este documento descreve as diretrizes de identidade visual do **EmpireMuse**, a paleta de cores "Nebulosa", os arquivos de marca oficiais e as instruções para aplicação no Discord Developer Portal.

---

## 1. Paleta de Cores "Nebulosa"

A identidade visual do EmpireMuse adota o conceito cósmico **Nebulosa**, combinando degradês de tons frios e quentes com o violeta como cor primária de destaque.

| Papel | Hex | Uso principal |
|---|---|---|
| Fundo (espaço profundo) | `#0B0A1F` | Fundo base escuro e contraste cósmico |
| Azul | `#3B82F6` | Transição fria e detalhes luminosos |
| **Violeta (cor principal / embeds)** | `#8B5CF6` | Cor primária da marca e padrão dos embeds |
| Magenta | `#C026D3` | Transição cromática e destaques vibrantes |
| Vermelho | `#E11D48` | Acentos quentes e energia visual |

---

## 2. Arquivos de Marca Oficiais (`assets/brand/`)

Todas as peças foram concebidas como arte original do EmpireMuse, sem dependência de ativos de terceiros ou logotipos do upstream.

- **`assets/brand/logo.svg`**: Emblema vetorial autocontido utilizado no cabeçalho do `README.md`. Possui fundo transparente fora do emblema e não contém scripts, estilos externos ou elementos dinâmicos.
- **`assets/brand/avatar.png`**: Ícone em formato PNG com resolução de **1024×1024** pixels (máximo 2 MB). A composição centraliza a silhueta da nebulosa e o elemento musical dentro do círculo focal, assegurando alta legibilidade mesmo em tamanhos reduzidos (32–40 px).
- **`assets/brand/banner.png`**: Banner panorâmico em formato PNG com resolução de **1500×600** pixels (proporção 5:2, máximo 4 MB), desenvolvido para personalização de perfil no Discord.

---

## 3. Configuração de Cores nos Embeds (`EMBED_COLOR`)

O bot permite personalizar a cor das mensagens incorporadas (embeds) através da variável de configuração `EMBED_COLOR` no arquivo `.env`:

- **Padrão**: `8B5CF6` (violeta da paleta Nebulosa).
- **Formatos aceitos**: hexadecimal de 6 dígitos, com ou sem `#` (ex.: `8B5CF6` ou `#8B5CF6`), sem distinção de maiúsculas e minúsculas.
- **Cor dinâmica do cargo**: defina `EMBED_COLOR=none` (ou deixe vazio) para que os embeds utilizem a cor do cargo mais alto do bot em cada servidor.

---

## 4. Como Aplicar Avatar e Banner no Discord Developer Portal

Para atualizar a imagem de perfil e o banner do seu bot:

1. Acesse o [Discord Developer Portal](https://discord.com/developers/applications) e faça login com sua conta.
2. Em **Applications**, selecione a aplicação do seu bot.
3. **Ícone da Aplicação**:
   - Acesse a aba **General Information** no menu lateral esquerdo.
   - Clique em **App Icon** e carregue o arquivo `assets/brand/avatar.png`.
   - Clique em **Save Changes**.
4. **Avatar e Banner do Bot**:
   - Acesse a aba **Bot** no menu lateral esquerdo.
   - Em **Icon**, carregue o arquivo `assets/brand/avatar.png`.
   - Em **Banner**, carregue o arquivo `assets/brand/banner.png`.
   - Clique em **Save Changes** no rodapé da tela para aplicar as alterações.

---

## 5. Recomendações para Instâncias Próprias (Self-Hosting)

Quem hospeda a própria instância do EmpireMuse deve se atentar a duas configurações essenciais no arquivo `.env`:

- **Servidor de suporte (`SUPPORT_SERVER`)**: Por padrão, aponta para o servidor oficial EmpireHUB. Quem hospeda a própria instância deve trocar pelo convite do próprio servidor ou deixar vazio (`SUPPORT_SERVER=''`) para não exibir o link no comando `/about` nem nos botões de erro.
- **Cor dos embeds (`EMBED_COLOR`)**: O padrão é o violeta `8B5CF6`. Para restaurar o comportamento clássico e utilizar a cor do cargo mais alto do bot no servidor, defina `EMBED_COLOR=none` (ou deixe vazio).

---

## 6. Padronização de Emojis Unicode

O EmpireMuse utiliza exclusivamente **emojis Unicode padronizados** para controles do player e identificação de fontes de música (YouTube, Spotify, Deezer, SoundCloud, Apple Music, Tidal, Last.fm etc.), em substituição aos emojis personalizados legados que dependiam de servidores externos do autor original e falhavam ao renderizar nos bots do EmpireMuse.

Além dos emojis universais, o nome da plataforma é exibido em texto explicativo onde antes havia apenas o ícone, assegurando renderização estável, acessibilidade a leitores de tela e visualização clara em qualquer tema ou plataforma do Discord.

