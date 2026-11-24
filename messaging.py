"""In-memory message bus. Agents talk to each other only through it; the feed is what the dashboard shows."""


class MessageBus:
    def __init__(self, keep=300, fold_cycles=6):
        self.fold_cycles = fold_cycles   # ASSUMPTION: an unchanged repeat within 3 hours folds into one entry
        self.inboxes = {}    # agent name -> messages waiting to be read
        self.feed = []       # feed entries, newest first, capped at `keep`
        self.latest = {}     # (sender, recipient, kind, topic) -> that thread's most recent feed entry
        self.keep = keep
        self.next_id = 1

    def register(self, name):
        """Give an agent an inbox."""
        self.inboxes.setdefault(name, [])

    def send(self, cycle, sender, recipient, kind, body, text, topic=None, signature=None):
        """Deliver to one agent, or to every other agent when recipient is 'all', and log it to the feed.

        kind: a short label the receiver dispatches on; body: structured data; text: a readable summary.
        topic: what the message is about (e.g. a cell id), so each topic has its own thread.
        signature: what makes the message news (defaults to its text). Every message is always
        delivered, but if a thread's message has the same signature as its previous entry and that
        entry is at most `fold_cycles` old, the feed folds it into that entry (cycle range and repeat
        count) instead of repeating it. Short breaks, e.g. a cell waiting one cycle on a noisy
        reading, don't start a new entry."""
        if recipient != 'all' and recipient not in self.inboxes:
            raise ValueError(f'Unknown recipient: {recipient}')
        message = dict(id=self.next_id, cycle=cycle, sender=sender, recipient=recipient, kind=kind, body=body, text=text)
        self.next_id += 1
        targets = [name for name in self.inboxes if name != sender] if recipient == 'all' else [recipient]
        for name in targets:
            self.inboxes[name].append(message)
        self._log(message, (sender, recipient, kind, topic), text if signature is None else signature)
        return message

    def _log(self, message, thread, signature):
        """Add a feed entry, or fold an unchanged repeat into the thread's recent entry."""
        last = self.latest.get(thread)
        still_shown = last is not None and self.feed and last['id'] >= self.feed[-1]['id']
        if still_shown and last['signature'] == signature and message['cycle'] - last['cycle'] <= self.fold_cycles:
            last.update(cycle=message['cycle'], text=message['text'], body=message['body'], repeats=last['repeats'] + 1)
            return
        entry = dict(message, first_cycle=message['cycle'], repeats=1, signature=signature)
        self.latest[thread] = entry
        self.feed.insert(0, entry)
        del self.feed[self.keep:]

    def receive(self, name):
        """Hand over, and clear, everything waiting for `name` (oldest first)."""
        messages, self.inboxes[name] = self.inboxes[name], []
        return messages
