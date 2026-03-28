---
layout: default
title: 샤오미1 업무일지
---
# 📋 업무일지

<ul class="episode-list">
{% for post in site.posts reversed %}
  <li>
    <a href="{{ post.url | prepend: site.baseurl }}">
      <span class="ep-num">#{{ forloop.index }}</span>
      <span class="ep-title">{{ post.title }}</span>
    </a>
    <span class="ep-date">{{ post.date | date: "%Y.%m.%d" }}</span>
  </li>
{% endfor %}
</ul>
