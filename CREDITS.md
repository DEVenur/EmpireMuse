# Créditos

## Origem do projeto

**EmpireMuse** é uma obra derivada do
[MuseHeart-MusicBot](https://github.com/zRitsu/MuseHeart-MusicBot), criado por **zRitsu** e
distribuído sob a licença **GPL-2.0** (consulte o arquivo [`LICENSE`](LICENSE), que permanece
intacto). Como obra derivada, o EmpireMuse também é distribuído sob a GPL-2.0.

- Repositório original: <https://github.com/zRitsu/MuseHeart-MusicBot>
- Ponto de partida do fork: commit upstream `32f227e9`
- Repositório do EmpireMuse: <https://github.com/EmpireCommunity/EmpireMuse>

## Agradecimentos

Nosso agradecimento a **zRitsu** e a todas as pessoas que contribuíram com o
MuseHeart-MusicBot upstream. Sem esse trabalho, o EmpireMuse não existiria.

## Recursos espelhados

Alguns recursos externos dos quais o projeto depende foram espelhados em repositórios da
organização EmpireCommunity, para não depender de contas de terceiros. A origem de cada um
é preservada abaixo.

| Recurso | Origem | Espelho / local no EmpireMuse | Licença / observações |
| :--- | :--- | :--- | :--- |
| Binários do Lavalink (`EmpireMuse-LL-binaries`, release `0.0.3`) | zRitsu (repositório upstream de binários `LL-binaries` na release `0.0.1`); Lavalink oficial v4.2.2 (equipe lavalink-devs) e plugins oficiais | [EmpireCommunity/EmpireMuse-LL-binaries](https://github.com/EmpireCommunity/EmpireMuse-LL-binaries) `0.0.3` | Lavalink 4.2.2 oficial (licença MIT) com plugins oficiais espelhados (LavaSrc 4.8.3, youtube-plugin snapshot e lyrics 2.6.1); `application.yml` com cliente TV, OAuth desligado por padrão e log do `YoutubeOauth2Handler` em WARN; hashes verificados via SHA-256 no download; preserva o histórico das releases `0.0.1` e `0.0.2`. |
| Aplicativo de RPC (Rich Presence) | [zRitsu/MuseHeart-MusicBot-RPC-app](https://github.com/zRitsu/MuseHeart-MusicBot-RPC-app) | [EmpireCommunity/EmpireMuse-RPC-app](https://github.com/EmpireCommunity/EmpireMuse-RPC-app) | GPL-3.0. |
| Imagens em `assets/` | Upstream e serviços de terceiros | `assets/` | Substituição por arte própria planejada. |
| Lista de servidores Lavalink | Gist do upstream; servidores públicos via `lavalink.darrennathanael.com` | `data/lavalink_servers.ini` | O crédito consta no cabeçalho do arquivo. |
| Guias de uso | Wiki e gist do upstream | `docs/guides/` | Cada página traz a nota de adaptação com o link do upstream. |
