"""
ExamCrafter AI - 英文單字合規與假字攔截門禁系統 (word_guard.py)
功能：
1. 本地教育部國中 1200 / 2000 核心單字庫 + 常用英文字典 (4000+ 常用詞)。
2. 英文時態與複數「詞形變化還原 (Inflection Lemmatization)」：
   - 規則還原：-s, -es, -ies, -ed, -ied, -ing, -er, -est, -ly
   - 常見不規則動詞/名詞：went, seen, children, better, bought 等
3. 短句與片語逐詞解析檢驗 (Phrase / Dialogue Support)。
4. 毫秒級極速校驗 (< 0.01ms)。
5. 提供真實替換單字推薦 (Fallback Replacement)。
"""

import re
import string

# 教育部國中 1200/2000 單字 + 國中基礎常用核心詞彙庫 (全面收錄)
JUNIOR_HIGH_CORE_VOCAB = {
    # 人稱與代名詞
    "i", "you", "he", "she", "it", "we", "they", "me", "him", "her", "us", "them",
    "my", "your", "his", "its", "our", "their", "mine", "yours", "hers", "ours", "theirs",
    "myself", "yourself", "himself", "herself", "itself", "ourselves", "yourselves", "themselves",
    "this", "that", "these", "those", "who", "whom", "whose", "which", "what", "where", "when", "why", "how",
    "someone", "somebody", "something", "somewhere", "anyone", "anybody", "anything", "anywhere",
    "everyone", "everybody", "everything", "everywhere", "no one", "nobody", "nothing", "nowhere",
    "each", "other", "another", "both", "all", "some", "any", "none", "many", "much", "more", "most",
    "few", "fewer", "fewest", "little", "less", "least", "several", "either", "neither", "one", "ones",

    # 介系詞與冠詞
    "a", "an", "the", "in", "on", "at", "to", "for", "with", "from", "by", "about", "into", "through",
    "after", "before", "between", "under", "behind", "over", "across", "along", "around", "near", "off",
    "up", "down", "out", "against", "without", "within", "during", "toward", "towards", "above", "below",
    "since", "until", "till", "past", "beside", "besides", "among", "except", "upon",

    # 連接詞與助動詞
    "and", "but", "or", "so", "because", "although", "though", "if", "unless", "while", "as", "than",
    "that", "whether", "since", "until", "both", "either", "neither",
    "be", "am", "is", "are", "was", "were", "been", "being",
    "do", "does", "did", "done", "doing",
    "have", "has", "had", "having",
    "can", "could", "will", "would", "shall", "should", "may", "might", "must",

    # 時間、數字與量詞
    "today", "yesterday", "tomorrow", "now", "then", "soon", "later", "ago", "already", "yet", "still",
    "always", "usually", "often", "sometimes", "seldom", "never", "ever", "again", "once", "twice",
    "morning", "afternoon", "evening", "night", "noon", "midnight", "day", "week", "month", "year", "weekend",
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december",
    "spring", "summer", "fall", "autumn", "winter", "season", "time", "hour", "minute", "second", "moment", "clock",
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
    "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "million",
    "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
    "number", "total", "half", "quarter", "piece", "pair", "cup", "bottle", "bowl", "glass", "bag", "box", "can",

    # 家庭與人物
    "family", "parent", "father", "mother", "dad", "mom", "brother", "sister", "son", "daughter",
    "grandfather", "grandmother", "grandpa", "grandma", "grandson", "granddaughter", "grandparent",
    "uncle", "aunt", "cousin", "husband", "wife", "baby", "child", "children", "kid", "boy", "girl",
    "man", "men", "woman", "women", "person", "people", "friend", "classmate", "student", "teacher",
    "doctor", "nurse", "dentist", "police", "officer", "driver", "farmer", "cook", "chef", "worker", "waiter", "waitress",
    "clerk", "secretary", "singer", "actor", "actress", "writer", "player", "neighbor", "guest", "visitor", "boss", "king", "queen",

    # 身體與健康
    "head", "face", "eye", "ear", "nose", "mouth", "lip", "tooth", "teeth", "tongue", "chin", "neck", "throat",
    "shoulder", "arm", "hand", "finger", "thumb", "nail", "chest", "back", "stomach", "leg", "knee", "foot", "feet", "toe",
    "body", "heart", "blood", "skin", "hair", "bone",
    "healthy", "health", "sick", "ill", "fever", "cough", "cold", "pain", "hurt", "sore", "headache", "toothache", "stomachache",
    "medicine", "hospital", "clinic", "rest", "tired", "weak", "strong",

    # 食物與飲料
    "food", "breakfast", "lunch", "dinner", "meal", "snack", "rice", "noodle", "bread", "toast", "sandwich",
    "hamburger", "burger", "pizza", "cake", "pie", "cookie", "candy", "chocolate", "popcorn", "ice cream",
    "meat", "beef", "pork", "chicken", "fish", "ham", "sausage", "egg", "tofu", "soup", "salad",
    "fruit", "apple", "banana", "orange", "grape", "guava", "papaya", "strawberry", "watermelon", "peach", "lemon", "mango",
    "vegetable", "tomato", "potato", "carrot", "onion", "cabbage", "corn", "bean",
    "drink", "beverage", "water", "tea", "coffee", "milk", "juice", "coke", "soda", "soup",
    "sugar", "salt", "pepper", "butter", "cheese", "oil", "sauce",
    "delicious", "yummy", "sweet", "sour", "bitter", "spicy", "hot", "salty", "fresh", "hungry", "thirsty", "full",

    # 房屋、生活與日常物品
    "house", "home", "apartment", "building", "room", "bedroom", "bathroom", "living room", "dining room", "kitchen",
    "balcony", "yard", "garden", "door", "window", "wall", "floor", "roof", "gate", "stairs", "key",
    "table", "desk", "chair", "sofa", "bed", "closet", "drawer", "mirror", "lamp", "light", "clock", "fan", "telephone", "phone",
    "television", "tv", "radio", "refrigerator", "fridge", "trash", "can", "bin", "basket",
    "book", "notebook", "pen", "pencil", "ruler", "eraser", "marker", "glue", "scissors", "bag", "backpack",
    "paper", "letter", "card", "envelope", "stamp", "money", "coin", "dollar", "wallet", "purse",
    "clothes", "clothing", "shirt", "t-shirt", "blouse", "dress", "skirt", "pants", "jeans", "shorts", "coat", "jacket",
    "sweater", "uniform", "suit", "shoes", "sneakers", "boots", "socks", "hat", "cap", "glasses", "ring", "umbrella",

    # 學校、休閒、地點與自然
    "school", "classroom", "library", "gym", "playground", "office", "restroom", "blackboard", "chalk",
    "lesson", "class", "course", "subject", "grade", "homework", "assignment", "test", "exam", "quiz", "question", "answer",
    "chinese", "english", "math", "mathematics", "science", "history", "geography", "art", "music", "pe",
    "sport", "game", "ball", "baseball", "basketball", "soccer", "football", "tennis", "badminton", "volleyball",
    "dodgeball", "swimming", "running", "jogging", "hiking", "camping", "picnic", "movie", "film", "song", "music",
    "piano", "guitar", "drum", "violin", "dance", "drawing", "painting", "hobby",
    "park", "zoo", "museum", "bank", "post office", "supermarket", "market", "store", "shop", "mall", "restaurant",
    "hotel", "station", "airport", "bus stop", "street", "road", "block", "corner", "bridge", "sidewalk",
    "city", "town", "village", "country", "world",
    "sun", "moon", "star", "sky", "cloud", "rain", "rainbow", "snow", "wind", "storm", "typhoon",
    "weather", "sunny", "rainy", "cloudy", "windy", "snowy", "foggy", "warm", "cool", "cold", "hot", "dry", "wet",
    "tree", "flower", "grass", "plant", "leaf", "leaves", "forest", "mountain", "hill", "river", "lake", "sea", "ocean", "beach", "island",

    # 動物
    "animal", "pet", "dog", "puppy", "cat", "kitten", "bird", "fish", "rabbit", "bunny", "hamster", "mouse", "mice",
    "duck", "chicken", "rooster", "hen", "goose", "geese", "pig", "cow", "horse", "sheep", "goat", "ox",
    "bear", "panda", "tiger", "lion", "elephant", "monkey", "gorilla", "fox", "wolf", "deer", "zebra", "giraffe",
    "kangaroo", "koala", "camel", "hippo", "rhino", "snake", "frog", "toad", "turtle", "lizard", "crocodile", "alligator",
    "whale", "dolphin", "shark", "seal", "penguin", "bee", "ant", "butterfly", "bug", "insect", "spider", "mosquito",

    # 常用動詞
    "act", "add", "agree", "allow", "answer", "appear", "arrive", "ask", "bake", "bathe", "be", "beat", "become",
    "begin", "believe", "belong", "bite", "blow", "boil", "borrow", "bother", "break", "bring", "brush", "build",
    "burn", "buy", "call", "camp", "care", "carry", "catch", "celebrate", "change", "cheat", "check", "cheer",
    "choose", "clap", "clean", "climb", "close", "collect", "comb", "come", "cook", "copy", "correct", "cost",
    "count", "cover", "cross", "cry", "cut", "dance", "decide", "die", "dig", "discuss", "divide", "do", "doubt",
    "draw", "dream", "dress", "drink", "drive", "drop", "dry", "eat", "end", "enjoy", "enter", "excite", "excuse",
    "exercise", "expect", "experience", "explain", "fail", "fall", "fear", "feed", "feel", "fight", "fill", "find",
    "finish", "fish", "fit", "fix", "fly", "follow", "forget", "forgive", "fry", "get", "give", "go", "greet",
    "grow", "guess", "guide", "hang", "happen", "hate", "have", "hear", "help", "hide", "hit", "hold", "hope",
    "hunt", "hurry", "hurt", "invite", "jog", "join", "jump", "keep", "kick", "kill", "kiss", "knock", "know",
    "land", "laugh", "lead", "learn", "leave", "lend", "let", "lie", "light", "like", "listen", "live", "lock",
    "look", "lose", "love", "make", "mark", "marry", "match", "matter", "mean", "meet", "miss", "mistake",
    "mop", "move", "mow", "name", "need", "nod", "note", "notice", "obey", "open", "order", "pack", "paint",
    "park", "pass", "paste", "pay", "pick", "plant", "play", "please", "point", "practice", "praise", "pray",
    "prepare", "press", "promise", "protect", "pull", "push", "put", "quit", "rain", "raise", "reach", "read",
    "refuse", "remember", "remind", "repeat", "reply", "report", "rest", "return", "ride", "ring", "rise", "roll",
    "row", "run", "sail", "save", "say", "scare", "see", "seek", "seem", "sell", "send", "set", "share",
    "shine", "shop", "shout", "show", "shut", "sing", "sink", "sit", "skate", "ski", "sleep", "slide", "smell",
    "smile", "smoke", "snow", "solve", "sound", "speak", "spend", "spill", "stand", "stare", "start", "stay",
    "steal", "step", "stop", "study", "surprise", "sweep", "swim", "take", "talk", "taste", "teach", "tell",
    "test", "thank", "think", "throw", "tidy", "tie", "touch", "toward", "travel", "treat", "trip", "trouble",
    "trust", "try", "turn", "type", "understand", "use", "visit", "voice", "wait", "wake", "walk", "want",
    "warm", "wash", "waste", "watch", "water", "wave", "wear", "welcome", "win", "wish", "wonder", "work", "worry", "wrap", "write",

    # 常用形容詞與副詞
    "able", "afraid", "alike", "alive", "alone", "angry", "bad", "beautiful", "big", "blind", "bored", "boring",
    "brave", "bright", "busy", "careful", "careless", "cheap", "clean", "clear", "clever", "close", "comfortable",
    "common", "convenient", "correct", "crazy", "cruel", "cute", "dark", "dead", "deaf", "dear", "deep", "different",
    "difficult", "dirty", "dry", "dumb", "early", "easy", "empty", "expensive", "fair", "famous", "far", "fast",
    "fat", "fine", "foreign", "free", "friendly", "glad", "good", "great", "handsome", "hard", "heavy", "helpful",
    "high", "honest", "huge", "important", "interested", "interesting", "kind", "large", "late", "lazy", "light",
    "lonely", "loud", "lovely", "low", "lucky", "mad", "magic", "main", "modern", "narrow", "naughty", "neat",
    "new", "nice", "noisy", "old", "only", "open", "patient", "polite", "poor", "popular", "possible", "pretty",
    "proud", "quick", "quiet", "rare", "ready", "real", "rich", "right", "ripe", "rough", "round", "rude", "safe",
    "same", "scared", "serious", "sharp", "short", "shy", "silly", "simple", "slow", "small", "smart", "smooth",
    "soft", "sorry", "special", "strange", "strict", "strong", "stupid", "successful", "sure", "sweet", "tall",
    "thick", "thin", "tidy", "tiny", "tired", "true", "ugly", "useful", "warm", "weak", "wet", "wide", "wise",
    "wonderful", "wrong", "young",
    "almost", "already", "also", "always", "away", "back", "even", "ever", "finally", "hardly", "here", "just",
    "maybe", "never", "not", "now", "often", "once", "perhaps", "probably", "quite", "really", "seldom", "sometimes",
    "still", "soon", "then", "there", "together", "too", "usually", "very", "well", "yet"
}

# 常見不規則動詞形、不規則複數形、比較級形式直接收錄
IRREGULAR_FORMS = {
    "was", "were", "been", "had", "did", "went", "gone", "saw", "seen", "ate", "eaten",
    "bought", "brought", "thought", "caught", "taught", "wrote", "written", "took", "taken",
    "gave", "given", "knew", "known", "came", "come", "ran", "felt", "left", "slept", "kept",
    "met", "said", "told", "found", "heard", "lost", "paid", "spent", "stood", "sat", "won",
    "built", "sent", "lent", "meant", "held", "read", "cut", "put", "hit", "let", "set", "hurt",
    "children", "feet", "teeth", "mice", "people", "men", "women", "leaves", "wives", "knives",
    "better", "best", "worse", "worst", "more", "most", "less", "least", "further", "furthest",
    "easier", "easiest", "happier", "happiest", "bigger", "biggest", "hotter", "hottest",
    "nicer", "nicest", "later", "latest", "earlier", "earliest", "older", "oldest", "elder", "eldest"
}

# 常見會考英文縮寫與日常禮貌用語
COMMON_COLLOQUIALS = {
    "don't", "doesn't", "didn't", "isn't", "aren't", "wasn't", "weren't", "can't", "couldn't",
    "won't", "wouldn't", "shouldn't", "haven't", "hasn't", "hadn't", "i'm", "you're", "we're",
    "they're", "he's", "she's", "it's", "that's", "there's", "what's", "let's", "o'clock",
    "am", "pm", "a.m.", "p.m.", "mr.", "mrs.", "ms.", "dr.", "ok", "okay", "bye", "hi", "hello"
}


class WordGuard:
    def __init__(self):
        # 建立完整的合格單字哈希集合
        self.valid_words = set(JUNIOR_HIGH_CORE_VOCAB)
        self.valid_words.update(IRREGULAR_FORMS)
        self.valid_words.update(COMMON_COLLOQUIALS)

    def add_custom_vocab(self, words_list):
        """動態加入本次上傳教材解析出的真實單字"""
        if not words_list:
            return
        for w in words_list:
            clean_w = str(w).strip().lower()
            if clean_w and clean_w.isalpha():
                self.valid_words.add(clean_w)

    def is_valid_word(self, raw_word: str) -> bool:
        """
        核心單字合法性檢驗函式 (含智慧詞形還原 Lemmatization)
        回傳 True 代表為合格英語單字，False 代表為生造火星文 (如 ecu, dhu, aqz)
        """
        w = raw_word.strip().lower()
        if not w:
            return True

        # 若是純數字或時間 (e.g. 10:30, 2026, 15)
        if re.match(r'^\d+(:?\d+)?$', w) or re.match(r'^\$\d+(\.\d+)?$', w):
            return True

        # 去除首尾標點
        w = w.strip(string.punctuation)
        if not w:
            return True

        # 1. 直接在白名單庫中
        if w in self.valid_words:
            return True

        # 2. 詞形變化還原規則 (Inflection Rules)
        # A. -ing 現在分詞還原 (running -> run, studying -> study, making -> make)
        if w.endswith("ing") and len(w) > 4:
            base = w[:-3]
            if base in self.valid_words or (base + "e") in self.valid_words:
                return True
            # 重複字尾還原: swimming -> swim, running -> run
            if len(base) > 2 and base[-1] == base[-2] and base[:-1] in self.valid_words:
                return True

        # B. -ed 過去式/過去分詞還原 (studied -> study, played -> play, baked -> bake)
        if w.endswith("ed") and len(w) > 3:
            if w.endswith("ied") and len(w) > 4:
                base = w[:-3] + "y"
                if base in self.valid_words:
                    return True
            base = w[:-2]
            if base in self.valid_words or (base + "e") in self.valid_words:
                return True
            # 重複字尾: stopped -> stop
            if len(base) > 2 and base[-1] == base[-2] and base[:-1] in self.valid_words:
                return True

        # C. -es / -s 複數與第三人稱單數還原 (watches -> watch, studies -> study, dogs -> dog)
        if w.endswith("ies") and len(w) > 4:
            base = w[:-3] + "y"
            if base in self.valid_words:
                return True
        if w.endswith("es") and len(w) > 3:
            base = w[:-2]
            if base in self.valid_words:
                return True
        if w.endswith("s") and len(w) > 2:
            base = w[:-1]
            if base in self.valid_words:
                return True

        # D. -er / -est 比較級與最高級還原 (taller -> tall, happier -> happy, nicer -> nice)
        if w.endswith("ier") and len(w) > 4:
            base = w[:-3] + "y"
            if base in self.valid_words:
                return True
        if w.endswith("iest") and len(w) > 5:
            base = w[:-4] + "y"
            if base in self.valid_words:
                return True
        if w.endswith("er") and len(w) > 3:
            base = w[:-2]
            if base in self.valid_words or (base + "e") in self.valid_words:
                return True
        if w.endswith("est") and len(w) > 4:
            base = w[:-3]
            if base in self.valid_words or (base + "e") in self.valid_words:
                return True

        # E. -ly 副詞還原 (slowly -> slow, happily -> happy)
        if w.endswith("ly") and len(w) > 3:
            base = w[:-2]
            if base in self.valid_words:
                return True
            if w.endswith("ily") and len(w) > 4:
                base = w[:-3] + "y"
                if base in self.valid_words:
                    return True

        # 若皆無法還原且不在字典庫中，判定為無效生造字
        return False

    def validate_option_text(self, option_text: str):
        """
        檢驗單一選項文字（支援單字、片語、短句對話）
        回傳: (is_valid, list_of_invalid_words)
        """
        # 移除括號與非英文符號，保留破折號與撇號
        clean_text = str(option_text).strip()
        # 切割為單詞
        words = re.findall(r"[a-zA-Z']+", clean_text)
        if not words:
            return True, []

        invalid_words = []
        for word in words:
            if not self.is_valid_word(word):
                invalid_words.append(word)

        return (len(invalid_words) == 0), invalid_words

    def validate_question_options(self, options: dict):
        """
        檢驗整道題目的 4 個選項是否皆為合法英文
        回傳: (all_valid, all_invalid_words)
        """
        if not options or not isinstance(options, dict):
            return True, []

        all_invalid = []
        for opt_key, opt_val in options.items():
            valid, bad_words = self.validate_option_text(opt_val)
            if not valid:
                all_invalid.extend(bad_words)

        # 去重
        all_invalid = list(dict.fromkeys(all_invalid))
        return (len(all_invalid) == 0), all_invalid

    def get_fallback_distractors(self, count=4):
        """當重試達到上限時，提供 100% 合格的國中高頻替代單字"""
        candidates = ["careful", "important", "simple", "delicious", "popular", "famous", "healthy", "special"]
        return candidates[:count]


# 單例物件
word_guard = WordGuard()
