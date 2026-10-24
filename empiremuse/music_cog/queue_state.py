"""Estado compartilhado pelas etapas de `/queue move` e `/queue clear`."""


class MoveState:
    """Variáveis que passam de uma etapa para outra (antes, locais de `do_move`)."""

    __slots__ = (
        "absent_members",
        "amount",
        "bot",
        "case_sensitive",
        "duplicates",
        "filters",
        "final_filters",
        "indexes",
        "insert_func",
        "inter",
        "max_duration",
        "min_duration",
        "player",
        "playlist",
        "playlist_hyperlink",
        "position",
        "range_end",
        "range_start",
        "song_author",
        "song_list",
        "song_name",
        "t",
        "tracklist",
        "txt",
        "user",
    )

    def __init__(
        self,
        *,
        inter,
        position,
        song_name,
        song_author,
        user,
        duplicates,
        playlist,
        min_duration,
        max_duration,
        amount,
        range_start,
        range_end,
        absent_members,
        case_sensitive,
    ):
        self.inter = inter
        self.position = position
        self.song_name = song_name
        self.song_author = song_author
        self.user = user
        self.duplicates = duplicates
        self.playlist = playlist
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.amount = amount
        self.range_start = range_start
        self.range_end = range_end
        self.absent_members = absent_members
        self.case_sensitive = case_sensitive
        self.bot = None
        self.filters = None
        self.final_filters = None
        self.indexes = None
        self.insert_func = None
        self.player = None
        self.playlist_hyperlink = None
        self.song_list = None
        self.t = None
        self.tracklist = None
        self.txt = None


class ClearState:
    """Variáveis que passam de uma etapa para outra (antes, locais de `clear`)."""

    __slots__ = (
        "absent_members",
        "amount",
        "amount_counter",
        "deleted_tracks",
        "duplicated_titles",
        "duplicates",
        "filters",
        "final_filters",
        "inter",
        "max_duration",
        "min_duration",
        "player",
        "playlist",
        "playlist_hyperlink",
        "range_end",
        "range_start",
        "song_author",
        "song_list",
        "song_name",
        "tracklist",
        "txt",
        "user",
    )

    def __init__(
        self,
        *,
        inter,
        song_name,
        song_author,
        user,
        duplicates,
        playlist,
        min_duration,
        max_duration,
        amount,
        range_start,
        range_end,
        absent_members,
    ):
        self.inter = inter
        self.song_name = song_name
        self.song_author = song_author
        self.user = user
        self.duplicates = duplicates
        self.playlist = playlist
        self.min_duration = min_duration
        self.max_duration = max_duration
        self.amount = amount
        self.range_start = range_start
        self.range_end = range_end
        self.absent_members = absent_members
        self.amount_counter = None
        self.deleted_tracks = None
        self.duplicated_titles = None
        self.filters = None
        self.final_filters = None
        self.player = None
        self.playlist_hyperlink = None
        self.song_list = None
        self.tracklist = None
        self.txt = None
